// SSE-aware reverse proxy for OpenCode
// Maintains persistent SSE connections to the browser while reconnecting
// to the backend transparently on instance dispose / restart.
const http = require("http");

const PROXY_PORT = parseInt(process.env.PROXY_PORT || "3000", 10);
const BACKEND_PORT = parseInt(process.env.BACKEND_PORT || "3001", 10);
const BACKEND_HOST = "localhost";

// ── Regular HTTP proxy with retry ──────────────────────────────────────────
function proxyHTTP(req, res) {
  // Buffer the request body so we can replay it on retry
  const chunks = [];
  req.on("data", (chunk) => chunks.push(chunk));
  req.on("end", () => {
    const body = Buffer.concat(chunks);
    attemptProxy(req, res, body, 0);
  });
  req.on("error", () => {
    if (!res.headersSent) res.writeHead(502);
    res.end("Bad Gateway");
  });
}

const MAX_HTTP_RETRIES = 3;
const HTTP_RETRY_DELAYS = [500, 1000, 2000]; // ms

function attemptProxy(req, res, body, attempt) {
  const proxyReq = http.request(
    {
      hostname: BACKEND_HOST,
      port: BACKEND_PORT,
      path: req.url,
      method: req.method,
      headers: { ...req.headers, host: `${BACKEND_HOST}:${BACKEND_PORT}` },
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    },
  );
  proxyReq.on("error", () => {
    if (attempt < MAX_HTTP_RETRIES) {
      const delay = HTTP_RETRY_DELAYS[attempt] || 2000;
      console.log(
        `[proxy] HTTP ${req.method} ${req.url} failed (attempt ${attempt + 1}/${MAX_HTTP_RETRIES}), retrying in ${delay}ms…`,
      );
      setTimeout(() => attemptProxy(req, res, body, attempt + 1), delay);
    } else {
      console.log(
        `[proxy] HTTP ${req.method} ${req.url} failed after ${MAX_HTTP_RETRIES} retries`,
      );
      if (!res.headersSent) res.writeHead(502);
      res.end("Bad Gateway");
    }
  });
  if (body.length) proxyReq.write(body);
  proxyReq.end();
}

// ── SSE proxy with automatic backend reconnection ───────────────────────────
function proxySSE(req, res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
    "Access-Control-Allow-Origin": req.headers.origin || "*",
    "Access-Control-Allow-Credentials": "true",
  });

  let alive = true;

  // Keep the browser connection alive while we reconnect to the backend
  const heartbeat = setInterval(() => {
    if (!alive) return;
    res.write(
      `data: ${JSON.stringify({ type: "server.heartbeat", properties: {} })}\n\n`,
    );
  }, 25000);

  req.on("close", () => {
    alive = false;
    clearInterval(heartbeat);
  });

  function connectBackend() {
    if (!alive) return;

    const backendReq = http.request(
      {
        hostname: BACKEND_HOST,
        port: BACKEND_PORT,
        path: "/event",
        method: "GET",
        headers: {
          ...req.headers,
          host: `${BACKEND_HOST}:${BACKEND_PORT}`,
          accept: "text/event-stream",
        },
      },
      (backendRes) => {
        if (backendRes.statusCode !== 200) {
          backendRes.resume(); // drain
          if (alive) setTimeout(connectBackend, 2000);
          return;
        }

        backendRes.on("data", (chunk) => {
          if (alive) res.write(chunk);
        });

        backendRes.on("end", () => {
          if (alive) {
            console.log("[proxy] Backend SSE closed, reconnecting in 1s…");
            setTimeout(connectBackend, 1000);
          }
        });

        backendRes.on("error", () => {
          if (alive) {
            console.log("[proxy] Backend SSE error, reconnecting in 2s…");
            setTimeout(connectBackend, 2000);
          }
        });
      },
    );

    backendReq.on("error", () => {
      if (alive) {
        console.log("[proxy] Backend unreachable, retrying in 2s…");
        setTimeout(connectBackend, 2000);
      }
    });

    backendReq.end();
  }

  connectBackend();
}

// ── HTTP server ─────────────────────────────────────────────────────────────
const server = http.createServer((req, res) => {
  if (req.url.startsWith("/event") && req.method === "GET") {
    return proxySSE(req, res);
  }
  proxyHTTP(req, res);
});

// ── WebSocket upgrade proxy with connection retry ──────────────────────────
const MAX_WS_CONNECT_RETRIES = 3;
const WS_RETRY_DELAYS = [500, 1000, 2000];

server.on("upgrade", (req, socket, head) => {
  function attemptUpgrade(attempt) {
    if (socket.destroyed) return;

    const proxyReq = http.request({
      hostname: BACKEND_HOST,
      port: BACKEND_PORT,
      path: req.url,
      method: req.method,
      headers: { ...req.headers, host: `${BACKEND_HOST}:${BACKEND_PORT}` },
    });

    proxyReq.on("upgrade", (proxyRes, proxySocket, proxyHead) => {
      const statusLine = `HTTP/${proxyRes.httpVersion} ${proxyRes.statusCode} ${proxyRes.statusMessage}\r\n`;
      const hdrs = Object.entries(proxyRes.headers)
        .map(([k, v]) => `${k}: ${v}`)
        .join("\r\n");
      socket.write(statusLine + hdrs + "\r\n\r\n");
      if (proxyHead.length) socket.write(proxyHead);

      proxySocket.pipe(socket);
      socket.pipe(proxySocket);

      proxySocket.on("error", (err) => {
        console.log(`[proxy] WebSocket backend error: ${err.message}`);
        socket.destroy();
      });
      socket.on("error", (err) => {
        console.log(`[proxy] WebSocket client error: ${err.message}`);
        proxySocket.destroy();
      });
    });

    proxyReq.on("error", (err) => {
      if (attempt < MAX_WS_CONNECT_RETRIES && !socket.destroyed) {
        const delay = WS_RETRY_DELAYS[attempt] || 2000;
        console.log(
          `[proxy] WebSocket upgrade to ${req.url} failed (attempt ${attempt + 1}/${MAX_WS_CONNECT_RETRIES}): ${err.message}, retrying in ${delay}ms…`,
        );
        setTimeout(() => attemptUpgrade(attempt + 1), delay);
      } else {
        console.log(
          `[proxy] WebSocket upgrade to ${req.url} failed after ${MAX_WS_CONNECT_RETRIES} retries: ${err.message}`,
        );
        socket.destroy();
      }
    });

    if (head.length) proxyReq.write(head);
    proxyReq.end();
  }

  attemptUpgrade(0);
});

server.listen(PROXY_PORT, "0.0.0.0", () => {
  console.log(
    `[proxy] Listening on :${PROXY_PORT}, forwarding to :${BACKEND_PORT}`,
  );
});

