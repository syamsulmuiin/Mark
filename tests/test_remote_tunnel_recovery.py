import asyncio
from types import SimpleNamespace as NS
from dashboard import server as mod


def test_tunnel_retries_start_failure_and_recovers_exited_process(monkeypatch):
    async def scenario():
        events, delays = [], []
        state = {'enabled': True, 'starts': 0, 'stops': 0}
        class Process:
            dead = False
            def poll(self): return 1 if self.dead else None
        class Tunnel:
            process = None
            def start(self):
                state['starts'] += 1
                if state['starts'] <= 2:
                    raise RuntimeError('private-token-do-not-log')
                if self.process is None or self.process.dead:
                    self.process = Process()
                return 'https://example.test'
            def stop(self): state['stops'] += 1
        tunnel = Tunnel()
        async def sleep(delay):
            delays.append(delay)
            if state['starts'] == 3:
                tunnel.process.dead = True
            if state['starts'] >= 4:
                state['enabled'] = False
        monkeypatch.setattr(mod, 'cloudflare_enabled', lambda: state['enabled'])
        monkeypatch.setattr(mod, '_interaction_event', lambda name, **kw: events.append((name, kw)))
        monkeypatch.setattr(mod.asyncio, 'sleep', sleep)
        host = NS(_tunnel=tunnel, _public_url='')
        await mod.DashboardServer._start_remote_tunnel(host)
        assert state['starts'] == 4 and state['stops'] == 1
        assert delays[:2] == [2, 4]
        assert [fields['status'] for _, fields in events] == ['retrying', 'retrying', 'process_running', 'process_running']
        assert 'private-token' not in str(events)
    asyncio.run(scenario())


def test_tunnel_cancellation_stops_connector(monkeypatch):
    async def scenario():
        stops = []
        tunnel = NS(process=NS(poll=lambda: None), start=lambda: 'https://example.test', stop=lambda: stops.append(True))
        monkeypatch.setattr(mod, 'cloudflare_enabled', lambda: True)
        async def sleep(delay): raise asyncio.CancelledError()
        monkeypatch.setattr(mod.asyncio, 'sleep', sleep)
        host = NS(_tunnel=tunnel, _public_url='')
        try: await mod.DashboardServer._start_remote_tunnel(host)
        except asyncio.CancelledError: pass
        assert stops == [True] and host._public_url == ''
    asyncio.run(scenario())


def test_repeated_tunnel_failures_use_capped_backoff(monkeypatch):
    async def scenario():
        delays = []
        state = {'enabled': True}
        def start(): raise OSError('network unavailable')
        async def sleep(delay):
            delays.append(delay)
            if len(delays) == 7: state['enabled'] = False
        monkeypatch.setattr(mod, 'cloudflare_enabled', lambda: state['enabled'])
        monkeypatch.setattr(mod.asyncio, 'sleep', sleep)
        host = NS(_tunnel=NS(process=None, start=start, stop=lambda: None), _public_url='')
        await mod.DashboardServer._start_remote_tunnel(host)
        assert delays == [2, 4, 8, 16, 32, 60, 60]
    asyncio.run(scenario())


def test_api_shutdown_cancels_its_tunnel_supervisor(monkeypatch):
    async def scenario():
        started, stopped = asyncio.Event(), asyncio.Event()
        async def tunnel():
            started.set()
            try: await asyncio.Event().wait()
            finally: stopped.set()
        async def gc(): return None
        async def api(): await started.wait()
        monkeypatch.setattr(mod, '_DEPS_OK', True)
        monkeypatch.setattr(mod, 'uvicorn', NS(Config=lambda *a, **kw: NS(**kw), Server=lambda cfg: NS(serve=api)), raising=False)
        monkeypatch.setattr(mod, '_ensure_certs', lambda: None)
        monkeypatch.setattr(mod, '_ensure_network_access', lambda *a: None)
        host = NS(_serve_pairing_discovery=lambda: None, _start_remote_tunnel=tunnel,
                  _attachment_gc_loop=gc, _ssl_enabled=lambda: False, _ip='127.0.0.1', app=object())
        await mod.DashboardServer.serve(host)
        assert stopped.is_set()
    asyncio.run(scenario())
