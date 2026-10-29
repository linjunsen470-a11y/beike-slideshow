"""Minimal Beike MCP (Streamable HTTP) client. Never prints the API key."""
import json, re, time, urllib.request, urllib.error
from pathlib import Path

URL = 'https://building.ke.com/mcp'
CLI_VERSION = '0.2.28'
_active_key = ''  # Set only by Client; logging never opens the credential file.


class MCPError(RuntimeError):
    pass


def load_key():
    p = Path.home() / '.beike' / 'BEIKE_MCP_API_KEY'
    k = p.read_text(encoding='utf-8-sig').strip() if p.is_file() else ''
    if k.lower().startswith('bearer '):
        k = k.split(None, 1)[1].strip()
    if not k:
        raise MCPError('Missing or empty Beike API key file: ~/.beike/BEIKE_MCP_API_KEY')
    return k


def redact(text):
    """Remove the API key from any string that might be logged."""
    text = str(text)
    secret = _active_key
    if secret:
        text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(?i)bearer\s+\S+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)(authorization["\s:=]+)[^\s,}\]]+', r'\1[REDACTED]', text)
    return text


class Client:
    def __init__(self, url=URL, timeout=60, retries=3):
        global _active_key
        self.url, self.timeout, self.retries = url, timeout, retries
        self._key = load_key()
        _active_key = self._key
        self.session = None
        self._id = 0

    def _post(self, payload, expect_reply=True):
        body = json.dumps(payload).encode()
        hdr = {'User-Agent': f'beike-cli/{CLI_VERSION}', 'Authorization': 'Bearer ' + self._key, 'X-Beike-Cli-Version': CLI_VERSION,
               'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': '2025-03-26'}
        if self.session:
            hdr['X-Beike-Session-Id'] = self.session
            hdr['Mcp-Session-Id'] = self.session
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(self.url, data=body, headers=hdr, method='POST')
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    sid = r.headers.get('X-Beike-Session-Id') or r.headers.get('Mcp-Session-Id')
                    if sid:
                        self.session = sid
                    ctype = r.headers.get('Content-Type', '')
                    raw = r.read().decode('utf-8', 'replace')
                if not expect_reply:
                    return None
                return self._parse(raw, ctype, payload.get('id'))
            except urllib.error.HTTPError as e:
                snippet = ''
                try:
                    snippet = e.read().decode('utf-8', 'replace')[:240]
                except Exception:  # noqa: BLE001
                    snippet = ''
                last = MCPError(redact(
                    f'HTTP {e.code} from Beike MCP ({payload.get("method")})'
                    + (f': {snippet}' if snippet else '')))
                if e.code in (400, 401, 403, 404):
                    raise last
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = MCPError(redact(
                    f'Network error talking to Beike MCP: {type(e).__name__}: {e}'))
            time.sleep(1.5 * (attempt + 1))
        raise last

    @staticmethod
    def _parse(raw, ctype, want_id):
        raw = raw.replace('\r\n', '\n').replace('\r', '\n')
        msgs = []
        looks_sse = ('text/event-stream' in (ctype or '')
                     or raw.lstrip().startswith(('event:', 'data:', 'id:')))
        if looks_sse:
            data = []
            for line in raw.splitlines() + ['']:
                if line.startswith('data:'):
                    data.append(line[5:].lstrip())
                elif not line.strip() and data:
                    blob = '\n'.join(data).strip()
                    data = []
                    if not blob or blob == '[DONE]':
                        continue
                    try:
                        msgs.append(json.loads(blob))
                    except ValueError:
                        pass
        elif raw.strip():
            m = json.loads(raw)
            msgs = m if isinstance(m, list) else [m]
        want = None if want_id is None else str(want_id)
        chosen = None
        for m in msgs:
            if isinstance(m, dict) and str(m.get('id')) == want:
                chosen = m
                break
        if chosen is None and len(msgs) == 1 and isinstance(msgs[0], dict):
            if 'result' in msgs[0] or 'error' in msgs[0]:
                chosen = msgs[0]
        if chosen is None:
            raise MCPError('No JSON-RPC reply in MCP response')
        if 'error' in chosen:
            err = chosen['error']
            message = err.get('message') if isinstance(err, dict) else err
            raise MCPError(redact(f'MCP error: {message}'))
        return chosen.get('result')

    def rpc(self, method, params=None):
        self._id += 1
        return self._post({'jsonrpc': '2.0', 'id': self._id, 'method': method, 'params': params or {}})

    def connect(self):
        self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                'clientInfo': {'name': 'ke-slideshow-fetch', 'version': '1.0'}})
        self._post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, expect_reply=False)
        return self

    def tools(self):
        return self.rpc('tools/list').get('tools', [])

    def call(self, name, args, retries=5):
        for attempt in range(retries):
            gap = time.time() - getattr(self, '_last_call', 0)
            if gap < 3:
                time.sleep(3 - gap)
            self._last_call = time.time()
            res = self.rpc('tools/call', {'name': name, 'arguments': args})
            if not res.get('isError'):
                break
            txt = ' '.join(c.get('text', '') for c in res.get('content', []))
            if attempt == retries - 1 or not re.search(
                    r'unavailable|timeout|busy|稍后|繁忙|限流|too many|429', txt, re.I):
                raise MCPError(redact(f'Tool {name} error: {txt[:300]}'))
            time.sleep(min(30, 5 * 2 ** attempt))
        if res.get('structuredContent') is not None:
            return res['structuredContent']
        txt = ''.join(c.get('text', '') for c in res.get('content', []) if c.get('type') == 'text')
        try:
            return json.loads(txt)
        except ValueError:
            return txt


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Beike MCP: credentials only from ~/.beike/BEIKE_MCP_API_KEY')
    parser.add_argument('--list-tools', action='store_true', help='Connect and list actual tool names and argument fields')
    args = parser.parse_args()
    if args.list_tools:
        try:
            for tool in Client().connect().tools():
                fields = ', '.join(tool.get('inputSchema', {}).get('properties', {}))
                print(redact(f"{tool['name']}({fields})"))
        except (MCPError, OSError) as exc:
            parser.exit(1, redact(f'{exc}\n'))
    else:
        parser.print_help()
