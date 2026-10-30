"""
End-to-end test of the agent (no GUI) with a scripted fake LLM and a real headless browser.
Covers: analysis (+rerun cache hits, follow-up reanalyze to docx), scraping (+0-call rerun),
automation (user info template, for_each dedupe, write_output), software_test placeholder.

Usage (from repo root):
  PYTHONPATH="$PWD" .venv/Scripts/python .claude/skills/ecogent/scripts/e2e_fake_llm.py       .claude/skills/ecogent/site "<scratch dir>/home"
Prints "ALL OK" on success. Serves the site on 127.0.0.1:8765.
"""
import functools, http.server, json, re, sys, threading, os
from pathlib import Path
SITE = Path(sys.argv[1]); HOME = Path(sys.argv[2]); WORK = HOME.parent / "work_folder"
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE)))
srv.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:8765"

from ecogent import llm as L, prompts as P
from ecogent.config import Settings
from ecogent.bridge import HeadlessBridge
from ecogent.core import EcogentAgent

CALLS = []
def fake_complete(self, system, messages, max_tokens=None):
    user = messages[-1]["content"]
    def r(obj): return L.LLMResponse(obj if isinstance(obj, str) else json.dumps(obj), len(system+user)//4, 50, "fake", "fake")
    if P.HEAL in system:
        CALLS.append("heal"); return r({"decision": "skip"})
    if P.INIT_SCHEMA in system and "ANALYSIS" in system:
        assert "read_file" in system and "extract_records" not in system and "upload" not in system
        CALLS.append("plan"); return r({"title":"Browser agent papers","summary":"s","reply":"Planning analysis.",
          "plan":{"goal":"summarize browser agent papers","destination":{"start_url":B+"/search.html"},
                  "output":{"format":"md","filename":"papers.md","instructions":"summary"}},
          "current_task":[{"id":"s1","action":"open_url","url":B+"/search.html"},
            {"id":"s2","action":"fill","target":"search box","value":"browser agent"},
            {"id":"s3","action":"click","target":"Search button"},
            {"id":"s4","action":"collect_links","target":"paper result titles","limit":3,"save_as":"papers"},
            {"id":"s5","action":"for_each","source":"papers","steps":[{"id":"a","action":"open_url","url":"{{item}}"},{"id":"b","action":"get_page_data"}]},
            {"id":"s6","action":"analyze","instructions":"short"}]})
    if P.INIT_SCHEMA in system and "AUTOMATION" in system:
        CALLS.append("plan"); return r({"title":"Apply jobs","summary":"s","reply":"ok",
          "plan":{"goal":"apply","destination":{"start_url":B+"/search.html"},"output":{"format":"csv","filename":"applied"},
                  "requirements":{"needs_login":False,"user_info_fields":["full_name"],"schedule":{"every_minutes":60}}},
          "current_task":[{"id":"s1","action":"open_url","url":B+"/search.html"},
            {"id":"s2","action":"fill","target":"search box","value":"{{user.full_name}}"},
            {"id":"s3","action":"click","target":"Search button","validation":{"url_contains":"Ada+Lovelace"}},
            {"id":"s4","action":"collect_links","target":"papers","limit":3,"save_as":"jobs"},
            {"id":"s5","action":"for_each","source":"jobs","dedupe":True,"steps":[{"id":"a","action":"open_url","url":"{{item}}"}]},
            {"id":"s6","action":"write_output"}]})
    if P.INIT_SCHEMA in system and "GENERAL BROWSER TASK" in system:
        assert "Selected folder for file tools: " + str(WORK) in user
        CALLS.append("plan"); return r({"title":"Local notes","summary":"s","reply":"ok",
          "plan":{"goal":"summarize local notes","output":{"format":"md","filename":"notes_summary"}},
          "current_task":[
            {"id":"f1","action":"list_files","pattern":"*","save_as":"docs"},
            {"id":"f2","action":"for_each","source":"docs","steps":[{"id":"r","action":"read_file","path":"{{item}}","as_data":True}]},
            {"id":"f3","action":"write_file","path":"out/hello.txt","value":"hello"},
            {"id":"f4","action":"append_file","path":"out/hello.txt","value":" world"},
            {"id":"f5","action":"copy_file","path":"out/hello.txt","dest":"backup/hello.txt"},
            {"id":"f6","action":"move_file","path":"backup/hello.txt","dest":"backup/renamed.txt"},
            {"id":"f7","action":"file_exists","path":"backup/renamed.txt","save_as":"ok"},
            {"id":"f8","action":"write_file","path":"out/check.txt","value":"exists={{ok}}"},
            {"id":"f9","action":"delete_file","path":"backup"},
            {"id":"f10","action":"make_dir","path":"made"},
            {"id":"f11","action":"read_file","path":"C:/Windows/win.ini","on_fail":"skip"},
            {"id":"f12","action":"analyze","instructions":"short"}]})
    if P.INIT_SCHEMA in system and "SCRAPING" in system:
        CALLS.append("plan"); return r({"title":"Baby products","summary":"s","reply":"ok",
          "plan":{"goal":"baby products under $50","destination":{"start_url":B+"/products.html"},
                  "output":{"format":"xlsx","filename":"baby.xlsx"},
                  "scrape":{"fields":[{"name":"title"},{"name":"price"},{"name":"url"}],"filters":[{"field":"price","op":"<","value":50}],"max_pages":5}},
          "current_task":[{"id":"s1","action":"open_url","url":B+"/products.html"},{"id":"s2","action":"extract_records"},{"id":"s3","action":"write_output"}]})
    if system == P.PICK:
        CALLS.append("pick")
        lines = user.split("Candidates:\n")[1].splitlines()
        want = "input" if '"fill"' in user else "button"
        idx = next(i for i,l in enumerate(lines) if f"<{want}" in l)
        return r({"index": idx})
    if system == P.PICK_LINKS:
        CALLS.append("links")
        idx = [int(m.group(1)) for m in re.finditer(r"\[(\d+)\] .*article", user)]
        return r({"indices": idx})
    if system == P.PATTERN:
        CALLS.append("pattern")
        assert "div.card" in user, user[:500]
        return r({"item_selector":"div.card","fields":{"title":{"selector":"h2.title","attr":"text"},"price":{"selector":"span.price","attr":"text"},"url":{"selector":"a","attr":"href"}},"pagination":"next","next_selector":"a.next"})
    if system == P.VALIDATE:
        CALLS.append("validate"); return r({"ok": True, "problems": ""})
    if system == P.ANALYZE_REDUCE:
        CALLS.append("analyze")
        if "notes one" in user:
            assert "sheet cell" in user and "docx paragraph" in user and '"k": "json value"' in user, user[:800]
            return r("# Notes\nok")
        assert "Paper 2" in user; return r("```markdown\n# Report\nThree papers.\n```")
    if P.FOLLOWUP_SCHEMA in system:
        CALLS.append("followup"); return r({"decision":"reanalyze","reply":"Converting to docx","summary":"s","plan_updates":{"output":{"format":"docx"}},"analysis_instructions":"docx","reuse_notes":True})
    raise AssertionError("unexpected prompt: " + system[:80])
L.LLMClient.complete = fake_complete

s = Settings(); s.home = str(HOME); s.headless = True; s.use_vector_memory = False; s.main_llm.api_key = "x"; s.ensure_dirs()
agent = EcogentAgent(s, HeadlessBridge(lambda t: print("  |", t)))
try:
    # ---- analysis
    a = agent.new_chat("analysis", headless=True)
    agent.handle_message(a.id, "Search papers about browser agents and summarize to md")
    a = agent.session(a.id)
    print("ANALYSIS status:", a.meta["status"], "calls:", CALLS)
    out = a.plan["data"]["output_file"]; print("output:", out, "->", Path(out).read_text()[:60].replace("\n"," | "))
    assert len(a.plan["data"]["temp_files"]) == 3
    CALLS.clear()
    agent.rerun(a.id)
    a = agent.session(a.id)
    print("RERUN status:", a.meta["status"], "calls:", CALLS, "stats:", a.plan["runs"][-1]["stats"])
    assert CALLS == ["analyze"], CALLS
    CALLS.clear()
    agent.handle_message(a.id, "give me the same as a Word document")
    a = agent.session(a.id)
    print("FOLLOWUP calls:", CALLS, "output:", a.plan["data"]["output_file"])
    assert a.plan["data"]["output_file"].endswith(".docx")
    # ---- scraping
    CALLS.clear()
    sc = agent.new_chat("scraping", headless=True)
    agent.handle_message(sc.id, "scrape baby products under $50")
    sc = agent.session(sc.id)
    print("SCRAPE status:", sc.meta["status"], "calls:", CALLS, "records:", sc.plan["data"]["records_count"], sc.plan["data"]["output_file"])
    assert sc.plan["data"]["records_count"] == 4, sc.plan["data"]   # $10.99..$40.99 across 2 pages
    CALLS.clear()
    agent.rerun(sc.id)
    sc = agent.session(sc.id)
    print("SCRAPE RERUN calls:", CALLS, "records:", sc.plan["data"]["records_count"])
    assert CALLS == []
    # ---- automation
    CALLS.clear()
    au = agent.new_chat("automation", headless=True)
    au.save_user_info({"full_name": "Ada Lovelace"})
    agent.handle_message(au.id, "apply to jobs")
    au = agent.session(au.id)
    print("AUTOMATION status:", au.meta["status"], "calls:", CALLS, "processed:", au.plan["data"]["processed"])
    assert au.meta["status"] == "done" and len(au.plan["data"]["processed"]["s5"]) == 3
    print(Path(au.plan["data"]["output_file"]).read_text())
    CALLS.clear()
    agent.rerun(au.id, scheduled=True)
    au = agent.session(au.id)
    print("AUTOMATION RERUN calls:", CALLS, "items_done:", au.plan["runs"][-1]["stats"]["items_done"])
    assert CALLS == [] and au.plan["runs"][-1]["stats"]["items_done"] == 0
    # ---- built-in file tools (others + selected folder)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "a_notes.txt").write_text("notes one", encoding="utf-8")
    (WORK / "b.json").write_text('{"k": "json value"}', encoding="utf-8")
    from openpyxl import Workbook
    wb = Workbook(); wb.active.append(["sheet cell", 1]); wb.save(WORK / "c.xlsx")
    from docx import Document
    d = Document(); d.add_paragraph("docx paragraph"); d.save(WORK / "d.docx")
    CALLS.clear()
    ot = agent.new_chat("others", headless=True)
    ot.update_meta(work_folder=str(WORK))
    agent.handle_message(ot.id, "summarize my local notes")
    ot = agent.session(ot.id)
    print("FILE TOOLS status:", ot.meta["status"], "calls:", CALLS)
    ex = ot.plan["execution"]["steps"]
    assert ex["f11"]["status"] == "failed" and "outside the allowed folders" in ex["f11"]["error"], ex["f11"]
    assert (WORK / "out/hello.txt").read_text() == "hello world"
    assert (WORK / "out/check.txt").read_text() == "exists=true"
    assert not (WORK / "backup").exists() and (WORK / "made").is_dir()
    assert len(ot.plan["data"]["temp_files"]) == 4, ot.plan["data"]["temp_files"]
    assert ot.meta["status"] == "done" and Path(ot.plan["data"]["output_file"]).exists()
    from ecogent import toolbox
    assert not toolbox.allowed("analyze", "scraping") and not toolbox.allowed("extract_records", "analysis")
    # ---- software test placeholder
    st = agent.new_chat("software_test", headless=True)
    CALLS.clear(); agent.handle_message(st.id, "test login page")
    print("SOFTWARE TEST reply:", agent.session(st.id).chat["messages"][-1]["text"], CALLS)
    assert CALLS == []
    print("ALL OK")
finally:
    agent.browser.close(); srv.shutdown()
