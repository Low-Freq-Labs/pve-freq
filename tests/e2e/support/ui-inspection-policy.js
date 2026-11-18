'use strict';

// Only browser entry, auth session, setup truth, and version reads are allowed.
// GET alone does not prove an operational API is harmless.
function allowedRequest(method, address, origin) {
  const url = new URL(address);
  if (url.origin !== origin || url.username || url.password) return false;
  const p = url.pathname;
  if (method === 'POST') return ['/api/auth/login', '/api/auth/logout'].includes(p) && !url.search;
  if (!['GET', 'HEAD'].includes(method)) return false;
  if (/^\/static\/(?:js|css|vendor)\/[a-zA-Z0-9_./-]+$/.test(p)) {
    return [...url.searchParams.keys()].every(key => key === 'v');
  }
  if (url.search) return false;
  return p === '/' || /^\/dashboard\/[a-z-]+$/.test(p) ||
    /^\/static\/(?:js|css|vendor)\/[a-zA-Z0-9_./-]+$/.test(p) || p === '/favicon.ico' ||
    ['/api/auth/verify', '/api/setup/status', '/api/info'].includes(p);
}
async function installInspectionPolicy(context, origin, blocked) {
  const refuse = route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({
    error: 'Blocked by UI inspection policy', inspection_blocked: true
  }) });
  await context.route('**/*', async route => {
    const request = route.request();
    const label = `${request.method()} ${new URL(request.url()).pathname}`;
    if (!allowedRequest(request.method(), request.url(), origin)) {
      blocked.add(label);
      return refuse(route);
    }
    let response;
    try {
      // route.continue() does not re-intercept redirect continuations. Never
      // follow a redirect, including one that could forward a login body.
      response = await route.fetch({ maxRedirects: 0, maxRetries: 0, timeout: 15_000 });
      if (response.status() >= 300 && response.status() < 400) {
        blocked.add(`REDIRECT ${response.status()} ${label}`);
        return await refuse(route);
      }
      return await route.fulfill({ response });
    } catch {
      // Fetch errors can contain request headers/body. Do not expose them to
      // Playwright reporters, including failures while posting credentials.
      blocked.add(`TRANSPORT FAILURE ${label}`);
      return await refuse(route).catch(() => {});
    } finally {
      if (response) await response.dispose().catch(() => {});
    }
  });
  await context.routeWebSocket('**/*', socket => {
    blocked.add('WEBSOCKET (blocked)');
    socket.close();
  });
}
module.exports = { allowedRequest, installInspectionPolicy };
