import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";

const PORT = Number(process.env.PORT || 8181);
const HOST = process.env.HOST || "0.0.0.0";
const OPS_API_URL = (process.env.OPS_API_URL || "http://vitrine_ops_api_hml:8080").replace(/\/$/, "");
const OPS_BROKER_URL = (process.env.OPS_BROKER_URL || "http://ops_broker:8770").replace(/\/$/, "");
const OPS_BROKER_TOKEN = process.env.OPS_BROKER_TOKEN || "";
const REQUEST_TIMEOUT_MS = Number(process.env.OPS_REQUEST_TIMEOUT_MS || 120000);

function authHeaders() {
  const headers = { Accept: "application/json", "Content-Type": "application/json" };
  if (OPS_BROKER_TOKEN) headers.Authorization = `Bearer ${OPS_BROKER_TOKEN}`;
  return headers;
}

async function upstream(base, method, path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${base}${path}`, {
      method,
      headers: authHeaders(),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    let payload;
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { detail: text.slice(0, 2000) };
    }
    if (!response.ok) {
      return { ok: false, status_code: response.status, body: payload };
    }
    return payload && typeof payload === "object" ? payload : { ok: true, data: payload };
  } catch (error) {
    return { ok: false, error: "upstream_unreachable", detail: error?.name || "Error", path };
  } finally {
    clearTimeout(timer);
  }
}

const api = (method, path, body) => upstream(OPS_API_URL, method, path, body);
const broker = (method, path, body) => upstream(OPS_BROKER_URL, method, path, body);

function reply(result, summary) {
  return {
    structuredContent: result,
    content: [{ type: "text", text: summary }],
  };
}

function createOpsServer() {
  const server = new McpServer(
    { name: "vitrine-vps-ops", version: "0.1.0" },
    {
      instructions:
        "Use read/status/health tools before mutating infrastructure. Never infer project IDs, paths, environments, or container names. This plugin exposes only named, allowlisted operations; it does not provide arbitrary shell access.",
    }
  );

  server.registerTool(
    "server_health",
    {
      title: "Server health",
      description: "Use this when the user wants to verify the health of the Vitrine Ops API before other infrastructure actions.",
      inputSchema: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      const result = await api("GET", "/health");
      return reply(result, result.ok === false ? "Ops API health check failed." : "Ops API is reachable.");
    }
  );

  server.registerTool(
    "project_status",
    {
      title: "Project status",
      description: "Use this when the user wants the current Git/workspace status for one known Vitrine project ID.",
      inputSchema: { project_id: z.string().min(1).max(80) },
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ project_id }) => {
      const result = await api("GET", `/projects/${encodeURIComponent(project_id)}/status`);
      return reply(result, result.ok === false ? `Could not read project ${project_id}.` : `Read status for ${project_id}.`);
    }
  );

  server.registerTool(
    "project_read_file",
    {
      title: "Read project file",
      description: "Use this when the user wants to inspect an allowlisted text file from a known Vitrine project repository. For operational shared data, use project_shared_read instead.",
      inputSchema: {
        project_id: z.string().min(1).max(80),
        path: z.string().min(1).max(300),
        start_line: z.number().int().min(1).max(1000000).default(1),
        end_line: z.number().int().min(1).max(1000000).default(400),
      },
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ project_id, path, start_line = 1, end_line = 400 }) => {
      const result = await api("POST", "/projects/read-file", { project_id, path, start_line, end_line });
      return reply(result, result.ok === false ? `Could not read ${path}.` : `Read ${path} from ${project_id}.`);
    }
  );

  server.registerTool(
    "project_shared_read",
    {
      title: "Read project shared data",
      description: "Use this when the user wants to inspect operational JSON, JSONL, log, CSV, Markdown, or text data from a shared directory explicitly declared in the project's manifest.",
      inputSchema: {
        project_id: z.string().min(1).max(80),
        shared_directory: z.string().regex(/^[A-Za-z0-9._-]+$/).max(80),
        path: z.string().min(1).max(300),
        start_line: z.number().int().min(1).max(1000000).default(1),
        end_line: z.number().int().min(1).max(1000000).default(400),
      },
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ project_id, shared_directory, path, start_line = 1, end_line = 400 }) => {
      const result = await api("POST", "/projects/shared/read", {
        project_id,
        shared_directory,
        path,
        start_line,
        end_line,
      });
      return reply(result, result.ok === false ? `Could not read shared/${shared_directory}/${path}.` : `Read shared/${shared_directory}/${path}.`);
    }
  );

  server.registerTool(
    "mcp_status",
    {
      title: "MCP runtime status",
      description: "Use this when the user wants the status of the fixed Vitrine MCP connector runtime. This does not accept arbitrary container or service names.",
      inputSchema: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      const result = await broker("POST", "/maintenance/mcp", { action: "status" });
      return reply(result, result.ok === false ? "Could not read MCP runtime status." : "Read MCP runtime status.");
    }
  );

  server.registerTool(
    "mcp_health",
    {
      title: "MCP runtime health",
      description: "Use this when the user wants to verify the fixed Vitrine MCP connector runtime health endpoint.",
      inputSchema: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      const result = await broker("POST", "/maintenance/mcp", { action: "health" });
      return reply(result, result.ok === false ? "MCP runtime health check failed." : "MCP runtime health check completed.");
    }
  );

  server.registerTool(
    "mcp_restart",
    {
      title: "Restart MCP runtime",
      description: "Use this only when the user explicitly wants to restart the fixed Vitrine MCP connector runtime after a validated change or when recovery requires it. No arbitrary service name is accepted.",
      inputSchema: { confirm: z.literal("EXECUTAR") },
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false, idempotentHint: false },
    },
    async ({ confirm }) => {
      if (confirm !== "EXECUTAR") return reply({ ok: false, error: "confirmation_required" }, "Restart not executed.");
      const result = await broker("POST", "/maintenance/mcp", { action: "restart" });
      return reply(result, result.ok === false ? "MCP runtime restart failed." : "MCP runtime restart requested.");
    }
  );

  return server;
}

const sessions = new Map();

const httpServer = createServer(async (req, res) => {
  if (req.url === "/health" && req.method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, service: "vitrine-vps-ops-plugin", version: "0.1.0" }));
    return;
  }

  if (req.url !== "/mcp") {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not_found" }));
    return;
  }

  const sessionId = req.headers["mcp-session-id"];
  let session = sessionId ? sessions.get(sessionId) : undefined;

  if (!session) {
    const server = createOpsServer();
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => randomUUID(),
      onsessioninitialized: (id) => sessions.set(id, { server, transport }),
    });
    transport.onclose = () => {
      for (const [id, value] of sessions.entries()) {
        if (value.transport === transport) sessions.delete(id);
      }
    };
    session = { server, transport };
    await server.connect(transport);
  }

  await session.transport.handleRequest(req, res);
});

httpServer.listen(PORT, HOST, () => {
  console.log(`VITRINE_VPS_OPS_PLUGIN=http://${HOST}:${PORT}/mcp`);
});
