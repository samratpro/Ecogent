"""
DearPyGui smoke test: opens the real window, loads a fake chat, opens every dialog and saves
screenshots (main.png, sample.png, newtask.png, settings.png, dialogs.png) into <out dir>.
Read the PNGs to check the layout. Prints "ERRORS: none" on success.

Usage: PYTHONPATH="$PWD" .venv/Scripts/python .claude/skills/ecogent/scripts/gui_smoke.py "<scratch dir>/gui"
"""
import sys, json
from pathlib import Path
import dearpygui.dearpygui as dpg
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
from ecogent import config
from ecogent.config import Settings
orig_load = Settings.load
def load():
    s = Settings(); s.home = str(OUT / "home"); s.use_vector_memory = False; s.ensure_dirs(); return s
Settings.load = staticmethod(load)
from ecogent.gui import app as A, dialogs as D
from ecogent.bridge import UIEvent

app = A.EcogentApp()
frame = {"n": 0}
real_render = dpg.render_dearpygui_frame
errors = []
def step():
    real_render(); frame["n"] += 1; n = frame["n"]
    try:
        if n == 5:
            s = app.worker.agent.new_chat("scraping", "Baby products test", "", True)
            s.save_plan({"goal": "test", "runs": [{"stats": {"cache_hits": 3}}]}); s.save_task([{"id": "s1", "action": "open_url", "url": "https://example.com"}])
            s.add_usage("plan", "fake", "m", 1200, 300)
            s.add_message("user", "Visit the shop and scrape baby products under $50")
            s.add_message("agent", "Plan ready: 3 steps.\nRun done: 3 steps ok | selector cache hits 1, LLM lookups 0")
            app.refresh_chats(); app.load_chat(s.id)
            app.events.put(UIEvent("log", payload={"text": "Browser ready (temp profile, headless mode)"}))
            app.events.put(UIEvent("busy", payload={"busy": True, "label": "Task message"}))
        if n == 30: dpg.output_frame_buffer(file=str(OUT / "main.png"))
        if n == 40:
            app.ui.request  # requests normally come from worker; simulate the event directly
            app.events.put(UIEvent("request", app.current, {"req_id": 1, "req_kind": "sample", "note": "6 records found",
                "rows": [{"title": f"Baby item {i}", "price": f"${10*i}.99", "url": f"https://x/p{i}"} for i in range(1, 5)]}))
        if n == 70: dpg.output_frame_buffer(file=str(OUT / "sample.png"))
        if n == 80:
            for d in list(app.request_dialogs): d.close()
            D.NewTaskDialog(app.settings, ["linkedin"], "", lambda r: None)
        if n == 110: dpg.output_frame_buffer(file=str(OUT / "newtask.png"))
        if n == 120:
            for item in dpg.get_windows():
                if dpg.get_item_configuration(item).get("modal"): dpg.delete_item(item)
            app.open_settings()
        if n == 150: dpg.output_frame_buffer(file=str(OUT / "settings.png"))
        if n == 160:
            for item in dpg.get_windows():
                if dpg.get_item_configuration(item).get("modal"): dpg.delete_item(item)
            D.HoldDialog("Possible captcha on https://example.com. Solve it in the browser, then press Continue.", lambda v: None)
            app.open_schedules(); app.open_profiles()
            D.UserInfoDialog(["full_name", "email", "resume_path"], "Information this automation will use", lambda r: None)
        if n == 190: dpg.output_frame_buffer(file=str(OUT / "dialogs.png"))
        if n == 200:
            for key in ("plan", "task", "steps", "memory"): app._load_json(key, force=True)
            app._load_files()
        if n == 215: dpg.stop_dearpygui()
    except Exception as e:
        import traceback; errors.append(traceback.format_exc()); dpg.stop_dearpygui()
dpg.render_dearpygui_frame = step
app.run()
print("frames:", frame["n"]); print("ERRORS:", errors or "none")
