"""
GUI -> worker -> browser integration: runs a scraping task through the DearPyGui app with a fake
LLM, auto-accepts the sample dialog, writes flow_sample.png / flow_done.png and the CSV.
Expect "chat: Baby products done" and "accepted sample via GUI: True".

Usage: PYTHONPATH="$PWD" .venv/Scripts/python .claude/skills/ecogent/scripts/gui_flow.py            .claude/skills/ecogent/site "<scratch dir>/flow"
"""
import sys, json, functools, http.server, threading, time
from pathlib import Path
import dearpygui.dearpygui as dpg
SITE, OUT = Path(sys.argv[1]), Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8766), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE)))
srv.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:8766"
from ecogent.config import Settings
def load():
    s = Settings(); s.home = str(OUT / "home"); s.use_vector_memory = False; s.headless = True; s.debug_port = 9241; s.main_llm.api_key = "x"; s.ensure_dirs(); return s
Settings.load = staticmethod(load)
from ecogent import llm as L, prompts as P
def fake(self, system, messages, max_tokens=None, json_mode=False):
    r = lambda o: L.LLMResponse(json.dumps(o), 500, 40, "fake", "fake")
    if P.INIT_SCHEMA in system:
        return r({"title": "Baby products", "summary": "s", "reply": "Plan ready.", "plan": {"goal": "baby under $50", "destination": {"start_url": B + "/products.html"},
          "output": {"format": "csv", "filename": "baby"}, "scrape": {"fields": [{"name": "title"}, {"name": "price"}], "filters": [{"field": "price", "op": "<", "value": 50}]}},
          "current_task": [{"id": "s1", "action": "open_url", "url": B + "/products.html"}, {"id": "s2", "action": "extract_records"}, {"id": "s3", "action": "write_output"}]})
    if system == P.PATTERN:
        return r({"item_selector": "div.card", "fields": {"title": {"selector": "h2.title", "attr": "text"}, "price": {"selector": "span.price", "attr": "text"}}, "pagination": "next", "next_selector": "a.next"})
    if system == P.VALIDATE: return r({"ok": True})
    raise AssertionError(system[:60])
L.LLMClient.complete = fake
from ecogent.gui import app as A, dialogs as D
app = A.EcogentApp()
st = {"n": 0, "accepted": False, "done": False, "t0": time.time()}
real = dpg.render_dearpygui_frame
def step():
    real(); st["n"] += 1; n = st["n"]
    if n == 5:
        app._create_task({"task_type": "scraping", "title": "", "profile": "", "headless": True, "prompt": "scrape baby products under $50"})
    for d in list(app.request_dialogs):
        if isinstance(d, D.SampleDialog) and dpg.is_item_shown(d.tag) and not st["accepted"]:
            dpg.output_frame_buffer(file=str(OUT / "flow_sample.png")); st["accepted"] = True; d.ok()
    if st["accepted"] and not app.worker.busy and not st["done"]:
        st["done"] = n
    if st["done"] and n == st["done"] + 30:
        dpg.output_frame_buffer(file=str(OUT / "flow_done.png"))
    if (st["done"] and n == st["done"] + 45) or time.time() - st["t0"] > 90:
        dpg.stop_dearpygui()
dpg.render_dearpygui_frame = step
app.run()
from ecogent.storage import ChatSession
for m in ChatSession.list_all(Path(OUT / "home" / "chats")): print("chat:", m["title"], m["status"])
print("accepted sample via GUI:", st["accepted"])
srv.shutdown()
