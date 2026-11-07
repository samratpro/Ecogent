"""
End-to-end test of the agent (no GUI) with a scripted fake LLM and a real headless browser.
Covers: analysis (local picks, 0-call rerun via the analysis cache, local docx conversion, LLM
follow-up, selector drift healed without the LLM, token budget), scraping (+0-call rerun),
automation (user info template, for_each dedupe, write_output), software_test placeholder,
plus unit checks of JSON repair, follow-up patches and page compaction.

Usage (from repo root):
  PYTHONPATH="$PWD" .venv/Scripts/python .claude/skills/ecogent/scripts/e2e_fake_llm.py       .claude/skills/ecogent/site "<scratch dir>/home"
Prints "ALL OK" on success. Serves the site on 127.0.0.1:8765.
"""
import functools, http.server, json, re, shutil, sys, threading, os
from pathlib import Path
HOME = Path(sys.argv[2]); WORK = HOME.parent / "work_folder"
SITE = HOME.parent / "site_copy"            # a copy: the drift test edits pages
shutil.rmtree(SITE, ignore_errors=True); shutil.copytree(sys.argv[1], SITE)
class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):                       # the drift test edits pages between runs
        self.send_header("Cache-Control", "no-store"); super().end_headers()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), functools.partial(NoCache, directory=str(SITE)))
srv.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:8765"

from ecogent import llm as L, prompts as P
from ecogent.config import Settings
from ecogent.bridge import HeadlessBridge
from ecogent.core import EcogentAgent

CALLS = []
def fake_complete(self, system, messages, max_tokens=None, json_mode=False):
    user = messages[-1]["content"]
    def r(obj): return L.LLMResponse(obj if isinstance(obj, str) else json.dumps(obj), len(system+user)//4, 50, "fake", "fake")
    if P.HEAL in system:
        CALLS.append("heal")
        if "Verification" in user or "code box" in user:            # rescue test: heal cannot fix it
            return r({"decision": "abort", "message": "the box is not visible"})
        if "_missing" in user:                                         # broken loop test
            return r({"decision": "abort", "message": "file does not exist"})
        return r({"decision": "skip"})
    if system == P.RESCUE:
        CALLS.append("rescue")
        assert "Elements:" in user and len(user) < 4000, user          # small view, no full page
        lines = user.split("Elements:\n")[1].splitlines()
        if "Moves so far: none" in user:
            return r({"do": "click", "index": next(i for i, l in enumerate(lines) if "Show form" in l), "final": False})
        return r({"do": "fill", "index": next(i for i, l in enumerate(lines) if "<input" in l), "value": "WRONG", "final": True})
    if system == P.LOCATE:
        CALLS.append("locate")   # like gpt-4o-mini on a hidden box: claims a human is needed
        return r({"selector": None, "need": "user", "reason": "the box is hidden; the user must click Show form"})
    if P.INIT_SCHEMA in system and "TYPO404" in user:
        CALLS.append("plan"); return r({"title": "Typo url", "summary": "s", "reply": "ok",
          "plan": {"goal": "read article one", "destination": {"start_url": B + "/articel1.html"}},
          "current_task": [{"id": "s1", "step_name": "Open article one", "action": "open_url", "url": B + "/articel1.html"},
                           {"id": "s2", "action": "get_page_data", "label": "a1"}]})
    if P.INIT_SCHEMA in system and "LOOPFAIL" in user:
        CALLS.append("plan"); return r({"title": "Broken loop", "summary": "s", "reply": "ok",
          "plan": {"goal": "read files"},
          "current_task": [{"id": "l1", "action": "list_files", "pattern": "*", "save_as": "docs"},
            {"id": "l2", "action": "for_each", "source": "docs", "steps": [
              {"id": "r", "action": "read_file", "path": "{{item}}_missing", "as_data": True}]}]})
    if P.INIT_SCHEMA in system and "RESCUEME" in user:
        CALLS.append("plan"); return r({"title": "Verify code", "summary": "s", "reply": "ok",
          "plan": {"goal": "enter the verification code", "destination": {"start_url": B + "/rescue.html"}},
          "current_task": [{"id": "s1", "action": "open_url", "url": B + "/rescue.html"},
            {"id": "s2", "action": "fill", "target": "verification code box", "value": "4242"},
            {"id": "s3", "action": "click", "target": "Send button", "validation": {"text_contains": "Verify"}}]})
    if P.INIT_SCHEMA in system and "ANALYSIS" in system and "PATCHME" in user:
        assert P.ADAPT_HINT in user and '"id": "s4"' in user, user[-600:]
        CALLS.append("plan"); return r({"title": "Patched", "summary": "s", "reply": "adapted",
          "plan_updates": {"output": {"filename": "patched.md"}},
          "step_changes": {"replace": [{"id": "s4", "limit": 2}]}})
    if P.INIT_SCHEMA in system and "ANALYSIS" in system:
        assert "read_file" in system and "extract_records" not in system and "upload" not in system
        CALLS.append("plan"); return r({"title":"Browser agent papers","summary":"s","reply":"Planning analysis.",
          "plan":{"goal":"summarize browser agent papers","destination":{"start_url":B+"/search.html"},
                  "output":{"format":"md","filename":"papers.md","instructions":"summary"}},
          "current_task":[{"id":"s1","action":"open_url","url":B+"/search.html"},
            {"id":"s2","action":"fill","target":"search box","value":"browser agent"},
            {"id":"s3","action":"click","target":"Search button"},
            {"id":"s4","action":"collect_links","target":"paper result titles","limit":3,"save_as":"papers"},
            {"id":"s5","action":"for_each","source":"papers","dedupe":True,"steps":[{"id":"a","action":"open_url","url":"{{item}}"},{"id":"b","action":"get_page_data"}]},
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
        idx = next((i for i,l in enumerate(lines) if f"<{want}" in l), -1)
        if idx < 0: return r({"index": -1, "need": "broader"})
        return r({"index": idx})
    if system == P.PICK_LINKS:
        CALLS.append("links")
        idx = [int(m.group(1)) for m in re.finditer(r"\[(\d+)\] .*article", user)]
        return r({"indices": idx})
    if system == P.PATTERN:
        CALLS.append("pattern")
        assert "div.card" in user, user[:500]
        return r({"item_selector":"div.card","fields":{"title":{"selector":"h2.title","attr":"text"},"price":{"selector":"span.price","attr":"text"},"url":{"selector":"a","attr":"href"}},"pagination":"next","next_selector":"a[href=\"/products2.html\"]"})  # page-specific, like real models
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

# ---- unit checks (no browser)
assert L.extract_json('{"a": [1, 2, {"b": "cut') == {"a": [1, 2, {"b": "cut"}]}          # truncated reply
assert L.extract_json("Sure! {'index': 2, 'ok': True,}") == {"index": 2, "ok": True}    # python-ish
from ecogent.core import apply_step_changes
old = [{"id": "s1", "action": "open_url"}, {"id": "s2", "action": "click", "target": "a"},
       {"id": "s3", "action": "for_each", "steps": [{"id": "x", "action": "open_url"}]}]
new = apply_step_changes(old, {"replace": [{"id": "s2", "target": "b"}], "remove": ["x"],
                               "insert_after": {"s1": [{"action": "wait"}, {"id": "s3", "action": "scroll"}], "^": [{"action": "wait"}]}})
assert [s["id"] for s in new] == ["n3", "s1", "n1", "n2", "s2", "s3"], new
assert new[4]["target"] == "b" and new[4]["action"] == "click" and new[5]["steps"] == []
from ecogent import page_reader as pr
html = ('<html><body><div class="css-1x2y3z wrapper"><div><div><nav><a href="/x">Menu</a></nav>'
        '<div class="cookie-banner">We use cookies. Accept all</div>'
        '<main><h1>Title</h1><p>Real content line that matters here.</p><a href="http://h.com/p?utm_source=x&id=7">Paper</a>'
        '<button class="Ab12Cd34">Search</button></main></div></div></div></body></html>')
outline = pr.page_outline(html)
assert "css-1x2y3z" not in outline and "Ab12Cd34" not in outline, outline
_, text = pr.main_text(html)
assert "cookies" not in text and "Real content" in text, text
assert pr.short_url("http://h.com/p?utm_source=x&id=7", "http://h.com/") == "/p?id=7"
c = pr.candidates(html, "click", "Search button", 1)
assert pr.obvious_choice(c, "click")["text"] == "Search", c
from ecogent import relevance as R
NL = chr(10)
filler = NL.join(f"Paragraph {i} about cooking recipes, gardening tips and travel stories." for i in range(200))
key = "Captcha challenges block scraping bots; courts debate the legal status of scraping."
docs, st = R.select([filler[:6000] + NL + key + NL + filler[6000:]], "legal issues of scraping and captcha bots", 3000)
assert st["after"] <= 3200 and key in docs[0], st          # relevant paragraph survives a 4x cut
assert R.select(["short"], "x", 3000)[0] == ["short"]       # within budget: untouched
big = NL.join([f"<div class=\"row\">filler line {i} about nothing</div>" for i in range(400)]
              + ["<form id=\"login\">", " <span>Newsletter signup</span>", "  <button>Subscribe now</button>"]
              + [f"<p>more filler {i}</p>" for i in range(200)])
fo = pr.focus_outline(big, "newsletter subscribe button", max_chars=1500)
assert 0 < len(fo) <= 1500 and "Subscribe now" in fo and '<form id="login">' in fo, fo   # match + ancestor
assert pr.focus_outline("<p>small</p>", "small") == ""                                   # small: use full
lk = ([{"text": f"Study {chr(65+i)}x{chr(70+i)} on agents", "href": f"http://h/p{i}", "chrome": False} for i in range(12)]
      + [{"text": f"Cited by {i}", "href": f"http://h/c{i}", "chrome": False} for i in range(12)]
      + [{"text": f"Menu {i}", "href": f"http://h/m{i}", "chrome": True} for i in range(5)])
off = pr.links_to_offer(lk, "paper result titles", 3)
assert [l["href"] for l in off] == [f"http://h/p{i}" for i in range(12)], off             # repeats + menu cut
assert len(pr.links_to_offer(lk, "cited by counts", 3)) == 24                           # hint names them: kept
assert len(pr.links_to_offer(lk[:4] + lk[-5:], "papers", 3)) == 9                       # too few: nothing cut
from ecogent.memory import normalize_request
assert normalize_request("Scrape  Books, under $20!") == normalize_request("scrape books under $20")
from ecogent.llm import LLMRouter
cs = Settings(); cs.local_llm.provider = "compatible"; cs.local_llm.base_url = "http://x"
rt = LLMRouter(cs)
assert rt._client_for("pick") is rt.local and rt._client_for("analyze_map") is rt.local
assert rt._client_for("plan") is rt.main and rt._client_for("analyze") is rt.main
login = '<html><head><title>Sign in - Shop</title></head><body><form><input name="user"><input type="password" name="pw"></form></body></html>'
assert pr.detect_login_wall(login, "https://shop.com/account/login?next=/orders")
assert not pr.detect_login_wall(login.replace('type="password"', 'type="password" hidden'), "https://shop.com/login")
assert not pr.detect_login_wall("<html><body><input type=password></body></html>", "https://shop.com/settings/security")
from ecogent import toolbox as TB
assert TB.guess({"action": "Browser", "url": "x"}, "scraping") == "open_url"
assert TB.guess({"action": "Page data", "label": "b", "step_name": "Extract book records"}, "scraping") == "extract_records"
assert TB.guess({"action": "Results"}, "scraping") == "write_output" and TB.guess({"action": "Results"}, "analysis") == "analyze"
assert TB.guess({"action": "Browser", "target": "Search button", "step_name": "click search"}, "analysis") == "click"
assert TB.guess({"action": "zzz"}, "analysis") == "" and "[Browser" not in TB.catalog("analysis")
from ecogent.core import _find_steps, ensure_deliverable
nested = {"plan": {"goal": "g", "current_task": [{"id": "s1", "action": "open_url"}]}}
assert _find_steps(nested) == [{"id": "s1", "action": "open_url"}] and "current_task" not in nested["plan"]
st = [{"id": "s1", "action": "open_url"}, {"id": "s2", "action": "extract_records"}]
ensure_deliverable(st, "scraping"); assert st[-1]["action"] == "write_output" and st[-1]["id"] == "s3", st
st = [{"id": "s1", "action": "for_each", "steps": [{"id": "b", "action": "get_page_data"}]}]
ensure_deliverable(st, "analysis"); assert st[-1]["action"] == "analyze", st
st = [{"id": "s1", "action": "extract_records"}, {"id": "s2", "action": "write_output"}]
ensure_deliverable(st, "scraping"); assert len(st) == 2
from ecogent.scraping import apply_pattern
card = '<div class="q"><span class="t">Hi</span><a class="tag">life</a><a class="tag">love</a></div>'
pat = {"item_selector": "div.q", "fields": {"text": {"selector": "span.t"}, "tags": {"selector": "a.tag", "many": True},
       "first": {"selector": "a.tag"}}}
assert apply_pattern(pat, card, "http://h/") == [{"text": "Hi", "tags": "life, love", "first": "life"}]
from ecogent.core import ensure_start
st = [{"id": "s1", "action": "fill", "target": "search box", "value": "x"}]
ensure_start(st, {"destination": {"start_url": "https://a.com"}})
assert st[0] == {"id": "s0", "step_name": "Open start page", "action": "open_url", "url": "https://a.com"}, st
st = [{"id": "s1", "action": "list_files"}]; ensure_start(st, {"destination": {"start_url": "https://a.com"}}); assert len(st) == 1
res = '<div class="r"><h3 class="t"><a href="/a1">One</a></h3></div>' * 1 + ''.join(
    f'<div class="r"><h3 class="t"><a href="/a{i}">Title {i}</a></h3></div>' for i in range(2, 5)) + '<nav><a href="/x">About</a></nav>'
assert [l["href"] for l in pr.result_group(pr.links(res, "http://h/"))] == ["http://h/a1", "http://h/a2", "http://h/a3", "http://h/a4"]
assert pr.result_group(pr.links('<a href="/1">a</a><a href="/2">b</a>', "http://h/")) == []
from ecogent import output as OUT
import tempfile, os
tmp = Path(tempfile.mkdtemp()) / "empty.csv"
assert OUT.write_rows([], tmp, columns=["title", "price"]).read_text(encoding="utf-8-sig").strip() == "title,price"
print("UNIT OK")

s = Settings(); s.home = str(HOME); s.headless = True; s.use_vector_memory = False; s.main_llm.api_key = "x"; s.ensure_dirs()
agent = EcogentAgent(s, HeadlessBridge(lambda t: print("  |", t)))
try:
    # ---- analysis
    a = agent.new_chat("analysis", headless=True)
    agent.handle_message(a.id, "Search papers about browser agents and summarize to md")
    a = agent.session(a.id)
    print("ANALYSIS status:", a.meta["status"], "calls:", CALLS, "stats:", a.plan["runs"][-1]["stats"])
    assert "pick" not in CALLS and a.plan["runs"][-1]["stats"]["local_picks"] == 2, CALLS   # obvious elements
    out = a.plan["data"]["output_file"]; print("output:", out, "->", Path(out).read_text()[:60].replace("\n"," | "))
    assert len(a.plan["data"]["temp_files"]) == 3
    CALLS.clear()
    agent.rerun(a.id)
    a = agent.session(a.id)
    print("RERUN status:", a.meta["status"], "calls:", CALLS, "stats:", a.plan["runs"][-1]["stats"])
    assert CALLS == [], CALLS          # same sources + same request: analysis reused
    CALLS.clear()
    agent.handle_message(a.id, "give me the same as a Word document")
    a = agent.session(a.id)
    print("FOLLOWUP (local) calls:", CALLS, "output:", a.plan["data"]["output_file"])
    assert CALLS == [] and a.plan["data"]["output_file"].endswith(".docx"), CALLS
    CALLS.clear()
    agent.handle_message(a.id, "focus more on token efficiency of each paper")
    a = agent.session(a.id)
    print("FOLLOWUP (LLM) calls:", CALLS)
    assert CALLS == ["followup", "analyze"], CALLS
    # ---- selector drift: the page layout changes; elements are re-found without the LLM
    page = SITE / "search.html"
    page.write_text(page.read_text().replace('<form', '<div class="top"><input type="text" name="email" '
        'placeholder="Your email"></div><div class="wrap"><form').replace('</form>', '</form></div>'))
    CALLS.clear(); agent.rerun(a.id); a = agent.session(a.id); st = a.plan["runs"][-1]["stats"]
    print("DRIFT RERUN calls:", CALLS, "stats:", st)
    assert a.meta["status"] == "done" and CALLS == [] and st["local_heals"] >= 1, (CALLS, st)
    page.write_text(page.read_text().replace(">Search</button>", ">Go</button>"))
    CALLS.clear(); agent.rerun(a.id); a = agent.session(a.id); st = a.plan["runs"][-1]["stats"]
    print("DRIFT 2 (button text changed) calls:", CALLS, "stats:", st)
    assert a.meta["status"] == "done" and CALLS == [], (CALLS, st)
    CALLS.clear(); agent.handle_message(a.id, "run it again")
    print("RERUN (local follow-up) calls:", CALLS)
    assert CALLS == [] and agent.session(a.id).meta["status"] == "done"
    # ---- same request in a NEW chat: the finished plan is reused, no planning call, warm selectors
    CALLS.clear()
    a2 = agent.new_chat("analysis", headless=True)
    agent.handle_message(a2.id, "search papers about browser agents, and summarize to MD")
    a2 = agent.session(a2.id); st = a2.plan["runs"][-1]["stats"]
    print("EXACT REPEAT status:", a2.meta["status"], "calls:", CALLS, "stats:", st)
    assert a2.meta["status"] == "done" and CALLS == [] and st["llm_lookups"] == 0, (CALLS, st)   # shared analysis cache
    assert len(a2.plan["data"]["temp_files"]) == 3
    # the earlier chat was switched to docx by a follow-up: the new chat gets what ITS request asks (md)
    assert a2.plan["data"]["output_file"].endswith(".md"), a2.plan["data"]["output_file"]
    # ---- similar request: the planner answers with a patch of the earlier plan
    CALLS.clear()
    a3 = agent.new_chat("analysis", headless=True)
    agent.handle_message(a3.id, "Search papers about browser agents and summarize to md PATCHME")
    a3 = agent.session(a3.id); st = a3.plan["runs"][-1]["stats"]
    print("PATCHED PLAN status:", a3.meta["status"], "calls:", CALLS, "output:", a3.plan["data"].get("output_file"))
    assert a3.meta["status"] == "done" and CALLS == ["plan", "analyze"], CALLS
    assert a3.plan["data"]["output_file"].endswith("patched.md") and len(a3.plan["data"]["temp_files"]) == 2
    assert [x["id"] for x in a3.current_task] == ["s1", "s2", "s3", "s4", "s5", "s6"]
    # ---- token budget: headless cannot approve more, so the run stops before the next LLM call
    s.max_run_tokens = 1
    b = agent.new_chat("analysis", headless=True)
    CALLS.clear(); agent.handle_message(b.id, "Collect web agent studies; md")
    b = agent.session(b.id)
    print("BUDGET status:", b.meta["status"], "calls:", CALLS)
    assert b.meta["status"] == "failed" and len(CALLS) == 2 and "analyze" not in CALLS, CALLS  # plan + 1 call, then stop
    s.max_run_tokens = 150000
    # ---- scraping
    CALLS.clear()
    sc = agent.new_chat("scraping", headless=True)
    agent.handle_message(sc.id, "scrape baby products under $50")
    sc = agent.session(sc.id)
    print("SCRAPE status:", sc.meta["status"], "calls:", CALLS, "records:", sc.plan["data"]["records_count"], sc.plan["data"]["output_file"])
    assert sc.plan["data"]["records_count"] == 6, sc.plan["data"]   # page 2 has no match: page 3 still scraped
    CALLS.clear()
    agent.rerun(sc.id)
    sc = agent.session(sc.id)
    print("SCRAPE RERUN calls:", CALLS, "records:", sc.plan["data"]["records_count"])
    assert CALLS == []
    CALLS.clear()
    sc2 = agent.new_chat("scraping", headless=True)
    agent.handle_message(sc2.id, "Scrape baby products under $50.")
    sc2 = agent.session(sc2.id)
    print("SCRAPE EXACT REPEAT calls:", CALLS, "records:", sc2.plan["data"]["records_count"])
    assert CALLS == [] and sc2.plan["data"]["records_count"] == 6 and sc2.meta["status"] == "done", CALLS
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
    # ---- a loop where EVERY item fails is a failed step, not "done"
    CALLS.clear()
    lf = agent.new_chat("others", headless=True)
    lf.update_meta(work_folder=str(WORK))
    agent.handle_message(lf.id, "read my files LOOPFAIL")
    lf = agent.session(lf.id); ex = lf.plan["execution"]["steps"]
    print("BROKEN LOOP status:", lf.meta["status"], "calls:", CALLS, "error:", ex["l2"].get("error", "")[:90])
    assert lf.meta["status"] == "failed" and "items all failed" in ex["l2"]["error"], (lf.meta, ex["l2"])
    assert CALLS.count("heal") == 3, CALLS                         # stopped after 3 of 4 items
    assert CALLS.count("heal") <= s.max_heals_per_run, CALLS        # bounded, no heal of the loop itself
    # ---- a guessed URL returns 404: the real page is found by its link, free, and saved
    CALLS.clear()
    ty = agent.new_chat("others", headless=True)
    agent.handle_message(ty.id, "read article one TYPO404")
    ty = agent.session(ty.id)
    print("TYPO 404 status:", ty.meta["status"], "calls:", CALLS, "url now:", ty.current_task[0]["url"])
    assert ty.meta["status"] == "done" and CALLS == ["plan"] and ty.current_task[0]["url"].endswith("/article1.html"), CALLS
    assert len(ty.plan["data"]["temp_files"]) == 1
    # ---- ReAct fallback: the code box is hidden until "Show form" is clicked; heal gives up
    CALLS.clear()
    rc = agent.new_chat("others", headless=True)
    agent.handle_message(rc.id, "enter my verification code RESCUEME")
    rc = agent.session(rc.id); st = rc.plan["runs"][-1]["stats"]
    print("RESCUE status:", rc.meta["status"], "calls:", CALLS, "stats:", st)
    assert rc.meta["status"] == "done" and CALLS.count("rescue") == 2 and st["rescued"] == 1, (CALLS, st)
    assert CALLS.count("pick") <= 1, CALLS          # the hidden box is never offered to the LLM
    assert agent.browser.page.input_value("input[name=code]") == "4242"      # the step's value, not the LLM's
    ids = [x["id"] for x in rc.current_task]
    assert ids == ["s1", "s2_r1", "s2", "s3"] and rc.current_task[1]["optional"], rc.current_task
    CALLS.clear(); agent.rerun(rc.id); rc = agent.session(rc.id); st = rc.plan["runs"][-1]["stats"]
    print("RESCUE RERUN calls:", CALLS, "stats:", st)
    assert rc.meta["status"] == "done" and CALLS == [] and st["rescued"] == 0, (CALLS, st)
    # the popup/prep element is gone next time: the optional prep step is skipped with no LLM call
    page = SITE / "rescue.html"
    page.write_text(page.read_text().replace('<button id="toggle"', '<button id="toggle" hidden')
                    .replace('style="display:none"', ''))
    CALLS.clear(); agent.rerun(rc.id); rc = agent.session(rc.id); st = rc.plan["runs"][-1]["stats"]
    print("RESCUE RERUN (no prep needed) calls:", CALLS, "stats:", st)
    assert rc.meta["status"] == "done" and CALLS == [] and st["steps_skipped"] == 1, (CALLS, st)
    # ---- software test placeholder
    st = agent.new_chat("software_test", headless=True)
    CALLS.clear(); agent.handle_message(st.id, "test login page")
    print("SOFTWARE TEST reply:", agent.session(st.id).chat["messages"][-1]["text"], CALLS)
    assert CALLS == []
    print("ALL OK")
finally:
    agent.browser.close(); srv.shutdown()
