#!/usr/bin/env python3
"""Claude Code 세션 JSONL → 세미나용 인터랙티브 로그 뷰어 HTML.

사용:
  python3 log2html.py --title "비개발 · 로드맵 진척 대시보드" --out pm-log.html main.jsonl [sidechain.jsonl ...]

- 여러 JSONL을 주면 timestamp 순으로 합친다. 첫 파일이 메인, 나머지는 서브에이전트(사이드체인)로 표시.
- 비밀값(토큰·키·DSN)은 <REDACTED>로 치환한다.
- 어시스턴트 텍스트에서 "[N] 단계명" / "현재 위치: N번" 패턴을 찾아 6단계 위치를 태깅한다.
"""
import argparse, html, json, re, sys, datetime
from pathlib import Path

STAGE_NAMES = {0:"맥락",1:"의도",2:"스펙",3:"분해",4:"구현",5:"검증",6:"개선"}
STAGE_PAT = re.compile(r"\[\s*([0-6])(?:\s*-\s*[ab])?\s*\]\s*(맥락|의도|스펙|분해|구현|검증|개선|게이트|사람|외부|심판)")
POS_PAT   = re.compile(r"현재\s*위치\s*[:：]\s*([0-6])\s*(?:번|-\s*[ab])")
FILE_PAT  = re.compile(r"(?<![\w.])([1-6])[ab]?-(?:의도|스펙|분해|구현|검증|개선|결과|리뷰시트)\.md")
LOOP_END  = re.compile(r"루프\s*[1-9]\s*(?:완료|종료)")
LOOP_PAT  = re.compile(r"루프\s*([1-9])\b")

# ── 비밀값 치환 ──────────────────────────────────────────────
SECRET_PATS = [
    (re.compile(r"https?://[A-Za-z0-9]{16,}@[^\s'\"]+"), "<REDACTED-DSN>"),          # sentry dsn
    (re.compile(r"\bphc_[A-Za-z0-9]{20,}\b"), "<REDACTED-POSTHOG-KEY>"),
    (re.compile(r"\bphx_[A-Za-z0-9]{20,}\b"), "<REDACTED-POSTHOG-KEY>"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "<REDACTED-KEY>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED-AWS-KEY>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "<REDACTED-GH-TOKEN>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"), "<REDACTED-SLACK>"),
    (re.compile(r"\bey[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\b"), "<REDACTED-JWT>"),
    (re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|dsn)(\s*[=:]\s*)['\"]?([A-Za-z0-9_\-\.\/+]{12,})"), r"\1\2<REDACTED>"),
    (re.compile(r"postgres(?:ql)?://[^\s'\"]+"), "postgres://<REDACTED>"),
]
def scrub(s: str) -> str:
    for p, r in SECRET_PATS:
        s = p.sub(r, s)
    return s

def esc(s): return html.escape(scrub(s or ""), quote=False)

def fmt_ts(ts):
    if not ts: return ""
    try:
        d = datetime.datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone()
        return d.strftime("%H:%M:%S")
    except Exception:
        return ts[11:19]

def short_input(name, inp):
    """tool_use 입력을 한 줄 요약."""
    if not isinstance(inp, dict): return esc(str(inp))[:160]
    for k in ("command","file_path","pattern","query","url","prompt","description","path"):
        if k in inp and isinstance(inp[k], str):
            v = inp[k].strip().replace("\n"," ⏎ ")
            return f"<b>{esc(k)}</b> {esc(v[:220])}{'…' if len(v)>220 else ''}"
    keys = ", ".join(list(inp.keys())[:5])
    return f"<span class=muted>{esc(keys)}</span>"

def block_text(c):
    if isinstance(c, str): return c
    if isinstance(c, list):
        out=[]
        for b in c:
            if isinstance(b, dict) and b.get("type")=="text": out.append(b.get("text",""))
            elif isinstance(b, str): out.append(b)
        return "\n".join(out)
    return ""

# ── JSONL 읽기 ───────────────────────────────────────────────
def load(path, lane):
    recs=[]
    with open(path, encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: r=json.loads(line)
            except Exception: continue
            if r.get("type") not in ("user","assistant"): continue
            if r.get("isMeta"): continue
            m=r.get("message") or {}
            recs.append({"lane":lane,"type":r["type"],"ts":r.get("timestamp",""),"content":m.get("content"),"uuid":r.get("uuid")})
    return recs

def add_prompt(ev, lane, ts, text):
    """사람 프롬프트 / 팀메이트 자동 알림 / 컨텍스트 압축 노트를 구분. 슬래시 명령 잔재는 버린다."""
    s=text.lstrip()
    if s.startswith(("<command-name>","<local-command-stdout>","/compact")): return
    if s.startswith("This session is being continued"):
        ev.append(dict(kind="note",lane=lane,ts=ts,text=text)); return
    who="📨 팀메이트 알림 (자동 수신)" if lane==0 and s.startswith(("Another Claude session sent a message","<teammate-message")) else None
    ev.append(dict(kind="prompt",lane=lane,ts=ts,text=text,who=who))

# ── 이벤트로 평탄화 ─────────────────────────────────────────
def flatten(recs):
    """각 레코드를 이벤트 리스트로: prompt / text / thinking / tool_use / tool_result"""
    ev=[]
    tool_names={}
    for r in recs:
        c=r["content"]; lane=r["lane"]; ts=r["ts"]
        if r["type"]=="user":
            if isinstance(c,str):
                if c.strip(): add_prompt(ev,lane,ts,c)
            else:
                for b in c or []:
                    if not isinstance(b,dict): continue
                    if b.get("type")=="tool_result":
                        cc=b.get("content"); txt=block_text(cc) if not isinstance(cc,str) else cc
                        ev.append(dict(kind="tool_result",lane=lane,ts=ts,text=txt or "",tool_id=b.get("tool_use_id"),is_error=bool(b.get("is_error"))))
                    elif b.get("type")=="text" and b.get("text","").strip():
                        add_prompt(ev,lane,ts,b["text"])
        else:
            for b in c or []:
                if not isinstance(b,dict): continue
                t=b.get("type")
                if t=="text" and b.get("text","").strip(): ev.append(dict(kind="text",lane=lane,ts=ts,text=b["text"]))
                elif t=="thinking" and b.get("thinking","").strip(): ev.append(dict(kind="thinking",lane=lane,ts=ts,text=b["thinking"]))
                elif t=="tool_use":
                    tool_names[b.get("id")]=b.get("name")
                    ev.append(dict(kind="tool_use",lane=lane,ts=ts,name=b.get("name"),input=b.get("input"),tool_id=b.get("id")))
    for e in ev:
        if e["kind"]=="tool_result": e["name"]=tool_names.get(e.get("tool_id"),"tool")
    return ev

def detect_stage(text):
    m=POS_PAT.search(text)
    if m: return int(m.group(1))
    ms=STAGE_PAT.findall(text)
    if ms: return int(ms[-1][0])
    return None

# ── 마크다운 최소 변환 (헤더·굵게·코드·표) ─────────────────
def md(text):
    text=scrub(text)
    lines=text.split("\n"); out=[]; in_code=False; in_table=False
    def inline(s):
        s=html.escape(s,quote=False)
        s=re.sub(r"`([^`]+)`",r"<code>\1</code>",s)
        s=re.sub(r"\*\*([^*]+)\*\*",r"<b>\1</b>",s)
        return s
    for ln in lines:
        if ln.strip().startswith("```"):
            if in_code: out.append("</code></pre>"); in_code=False
            else: out.append("<pre><code>"); in_code=True
            continue
        if in_code: out.append(html.escape(ln,quote=False)); continue
        if ln.strip().startswith("|") and ln.strip().endswith("|"):
            cells=[c.strip() for c in ln.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?",c) for c in cells if c): continue
            if not in_table: out.append("<table>"); in_table=True
            out.append("<tr>"+"".join(f"<td>{inline(c)}</td>" for c in cells)+"</tr>"); continue
        elif in_table: out.append("</table>"); in_table=False
        m=re.match(r"^(#{1,4})\s+(.*)",ln)
        if m: out.append(f"<h{min(len(m.group(1))+2,5)}>{inline(m.group(2))}</h{min(len(m.group(1))+2,5)}>"); continue
        m=re.match(r"^\s*[-*•]\s+(.*)",ln)
        if m: out.append(f"<div class=li>• {inline(m.group(1))}</div>"); continue
        m=re.match(r"^\s*(\d+)[.)]\s+(.*)",ln)
        if m: out.append(f"<div class=li>{m.group(1)}. {inline(m.group(2))}</div>"); continue
        if not ln.strip(): out.append("<div class=sp></div>"); continue
        out.append(f"<p>{inline(ln)}</p>")
    if in_code: out.append("</code></pre>")
    if in_table: out.append("</table>")
    return "\n".join(out)

# ── 렌더 ─────────────────────────────────────────────────────
def render(ev, title, subtitle, main_label, side_label):
    turns=[]; cur=None; stage=None; loop=1; bumped=False
    for e in ev:
        if e["kind"]=="prompt" and e["lane"]==0:
            cur=dict(prompt=e,items=[],stage=stage,ts=e["ts"],loop=loop); turns.append(cur); bumped=False; continue
        if cur is None:
            cur=dict(prompt=None,items=[],stage=stage,ts=e["ts"],loop=loop); turns.append(cur)
        if e["kind"]=="text" and e["lane"]==0:
            found=set(int(m[0]) for m in STAGE_PAT.findall(e["text"]))
            m=POS_PAT.search(e["text"])
            if m: found.add(int(m.group(1)))
            found.update(int(x) for x in FILE_PAT.findall(e["text"]))
            if LOOP_END.search(e["text"]): found.add(6)
            ln=[int(x) for x in LOOP_PAT.findall(e["text"])]
            if ln and max(ln)>loop: loop=max(ln); cur["loop"]=loop; bumped=True
            if found:
                if not bumped and stage==6 and min(found)<=1: loop+=1; cur["loop"]=loop; bumped=True  # 6 뒤에 0/1이 다시 나오면 새 루프
                cur.setdefault("stages",set()).update(found); stage=max(found); cur["stage_end"]=stage
        cur["items"].append(e)

    def toc_label(t):
        if not t["prompt"]: return "(계속)"
        if t["prompt"].get("who"): return "📨 팀메이트 알림"
        lines=[l.strip() for l in t["prompt"]["text"].splitlines() if l.strip()]
        pick=next((l for l in lines if l.startswith("목표")),None) or next((l for l in lines if not l.startswith(("/","~","-","•","*"))),lines[0] if lines else "")
        return pick[:40]

    # 통계
    n_prompt=sum(1 for t in turns if t["prompt"] and not t["prompt"].get("who"))
    n_tool=sum(1 for e in ev if e["kind"]=="tool_use")
    n_side=sum(1 for e in ev if e["lane"]>0)
    tool_counts={}
    for e in ev:
        if e["kind"]=="tool_use": tool_counts[e["name"]]=tool_counts.get(e["name"],0)+1
    top_tools=", ".join(f"{k} {v}" for k,v in sorted(tool_counts.items(),key=lambda x:-x[1])[:6])

    body=[]
    for i,t in enumerate(turns,1):
        st=t.get("stage_end", t["stage"])
        stages=sorted(t.get("stages") or ([st] if st is not None else []))
        pills='<span class="arw">→</span>'.join(f'<span class="stage s{s}">[{s}] {STAGE_NAMES[s]}</span>' for s in stages) or '<span class="stage">—</span>'
        stcls=f"s{st}" if st is not None else ""
        body.append(f'<article class="turn {stcls}" id="t{i}" data-stages="{",".join(map(str,stages))}">')
        loopbadge=f'<span class="lane">루프 {t["loop"]}</span>' if t.get("loop",1)>1 else ""
        body.append(f'<div class="thd"><span class="tn">#{i}</span>{loopbadge}'
                    f'{pills}'
                    f'<span class="ts">{fmt_ts(t["ts"])}</span></div>')
        if t["prompt"]:
            who=t["prompt"].get("who"); syscls=" sys" if who else ""
            body.append(f'<div class="msg human{syscls}"><div class="who">{who or "👤 사람 (조율자에게)"}</div><div class="bd">{md(t["prompt"]["text"])}</div>'
                        f'<button class="cp" data-cp>프롬프트 복사</button></div>')
        for e in t["items"]:
            lane=" side" if e["lane"]>0 else ""
            lanetag=f'<span class="lane">{side_label}</span>' if e["lane"]>0 else ""
            if e["kind"]=="text":
                body.append(f'<div class="msg ai{lane}"><div class="who">🤖 에이전트{lanetag}</div><div class="bd">{md(e["text"])}</div></div>')
            elif e["kind"]=="thinking":
                body.append(f'<details class="msg think{lane}"><summary>💭 생각{lanetag} <span class="muted">{len(e["text"])}자</span></summary><div class="bd">{md(e["text"])}</div></details>')
            elif e["kind"]=="tool_use":
                body.append(f'<div class="msg tool{lane}"><span class="tname">⚙ {esc(e["name"])}</span>{lanetag} <span class="targ">{short_input(e["name"],e["input"])}</span></div>')
            elif e["kind"]=="tool_result":
                txt=e["text"] or ""; n=len(txt); err=" err" if e.get("is_error") else ""
                if n==0: continue
                prev=txt[:4000]
                body.append(f'<details class="msg tres{err}{lane}"><summary>↳ 결과 <span class="muted">{esc(e.get("name",""))} · {n:,}자{" · 오류" if err else ""}</span></summary><pre>{esc(prev)}{"…" if n>4000 else ""}</pre></details>')
            elif e["kind"]=="note":
                body.append(f'<details class="msg note"><summary>🗜 컨텍스트 압축 <span class="muted">자동 요약 · {len(e["text"]):,}자 · 사람이 쓴 게 아님</span></summary><div class="bd">{md(e["text"])}</div></details>')
            elif e["kind"]=="prompt":  # sidechain prompt
                body.append(f'<div class="msg human side"><div class="who">📨 서브에이전트에게 준 프롬프트{lanetag}</div><div class="bd">{md(e["text"])}</div></div>')
        body.append("</article>")

    rail="".join(f'<button class="chip s{k}" data-st="{k}"><span class="k">{k}</span>{v}</button>' for k,v in STAGE_NAMES.items())
    toc="".join(f'<a href="#t{i}" class="toc {"s"+str(t.get("stage_end",t["stage"])) if t.get("stage_end",t["stage"]) is not None else ""}"><span>#{i}</span>{esc(toc_label(t))}</a>' for i,t in enumerate(turns,1))

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
:root{{--bg:#0e1014;--panel:#161a21;--panel2:#1d222b;--line:#2b313d;--text:#e9ecf2;--muted:#9aa4b5;--accent:#7cc4ff;--ctx:#b8a4ff;--verify:#ffb454;--danger:#ff6b6b;--ok:#6bd68f;--pm:#aab4c8;--st0:#b39dff;--st1:#6fb6ff;--st2:#4fd1d9;--st3:#6fd88f;--st4:#e8d566;--st5:#ffab4d;--st6:#ff7eb6}}
.s0{{--sc:var(--st0)}} .s1{{--sc:var(--st1)}} .s2{{--sc:var(--st2)}} .s3{{--sc:var(--st3)}} .s4{{--sc:var(--st4)}} .s5{{--sc:var(--st5)}} .s6{{--sc:var(--st6)}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 -apple-system,"Pretendard","Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif;letter-spacing:-.01em}}
code,pre{{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}}
header{{position:sticky;top:0;z-index:10;background:rgba(14,16,20,.9);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:12px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
header h1{{font-size:18px;margin:0;font-weight:800}} header .sub{{color:var(--muted);font-size:13px}}
.rail{{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}}
.chip{{appearance:none;border:1px solid var(--line);background:var(--panel2);color:var(--muted);font:inherit;font-size:13px;font-weight:700;padding:5px 10px;border-radius:999px;cursor:pointer;display:flex;gap:6px;align-items:center}}
.chip .k{{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:6px;background:var(--bg);font-size:11px;font-weight:800;color:var(--sc,var(--accent))}}
.chip.on{{border-color:var(--sc,var(--accent));color:var(--text);background:color-mix(in srgb,var(--sc,var(--accent)) 16%,var(--panel2))}} .chip.on .k{{background:var(--sc,var(--accent));color:#0e1014}} .chip.dim{{opacity:.35}}
.ctrl{{display:flex;gap:10px;align-items:center;font-size:13px;color:var(--muted);flex-wrap:wrap}}
.ctrl label{{display:flex;gap:4px;align-items:center;cursor:pointer}} .ctrl input[type=search]{{background:var(--panel2);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:5px 10px;font:inherit;font-size:13px;width:200px}}
.layout{{display:grid;grid-template-columns:260px 1fr;gap:0;max-width:1400px;margin:0 auto}}
@media(max-width:900px){{.layout{{grid-template-columns:1fr}} aside{{display:none}}}}
aside{{position:sticky;top:64px;align-self:start;height:calc(100vh - 64px);overflow:auto;padding:16px 12px;border-right:1px solid var(--line)}}
aside .stat{{font-size:12px;color:var(--muted);padding:0 8px 12px;border-bottom:1px solid var(--line);margin-bottom:10px;line-height:1.7}}
.toc{{display:flex;gap:8px;padding:6px 8px;border-radius:8px;color:var(--muted);text-decoration:none;font-size:13px;border-left:3px solid transparent}}
.toc{{border-left-color:var(--sc,transparent)}} .toc span{{color:var(--sc,var(--accent));font-weight:700;min-width:26px}} .toc:hover{{background:var(--panel2);color:var(--text)}}
main{{padding:20px 28px 120px;min-width:0}}
.turn{{border:1px solid var(--line);border-radius:14px;background:var(--panel);margin:0 0 18px;padding:14px 18px 10px;border-left:5px solid var(--sc,var(--line))}}
.turn.hide{{display:none}}
.thd{{display:flex;gap:12px;align-items:center;font-size:13px;color:var(--muted);margin-bottom:8px}} .thd .tn{{font-weight:800;color:var(--sc,var(--accent))}} .thd .stage{{font-weight:800;color:var(--sc,var(--text));background:color-mix(in srgb,var(--sc,var(--panel2)) 14%,var(--panel2));border:1px solid color-mix(in srgb,var(--sc,var(--line)) 55%,transparent);padding:2px 10px;border-radius:999px}} .thd .arw{{color:var(--muted);margin:0 -4px}} .thd .ts{{margin-left:auto}}
.msg{{margin:8px 0;border-radius:10px;padding:10px 14px;position:relative}}
.msg .who{{font-size:12px;font-weight:800;letter-spacing:.06em;color:var(--muted);margin-bottom:6px}}
.human{{background:rgba(124,196,255,.10);border:1px solid rgba(124,196,255,.35)}} .human .who{{color:var(--accent)}}
.ai{{background:var(--panel2);border:1px solid var(--line)}}
.think{{background:transparent;border:1px dashed var(--line);color:var(--muted);font-size:14px}} .think summary{{cursor:pointer;font-weight:700}} .think .bd{{margin-top:8px}}
.tool{{background:transparent;border:0;padding:4px 14px;font-size:13.5px;color:var(--muted)}} .tool .tname{{color:var(--ok);font-weight:700}} .tool .targ{{margin-left:8px}}
.tres{{background:#0a0c10;border:1px solid var(--line);font-size:13px}} .tres summary{{cursor:pointer;color:var(--muted);font-weight:700}} .tres pre{{margin:8px 0 0;white-space:pre-wrap;word-break:break-all;max-height:420px;overflow:auto;font-size:12.5px;line-height:1.5;color:#c9d0dc}} .tres.err{{border-color:rgba(255,107,107,.5)}}
.side{{margin-left:28px;border-left:3px dashed var(--pm)}} .msg.note{{opacity:.7}} .msg.human.sys .who{{color:var(--pm)}} .lane{{display:inline-block;font-size:11px;font-weight:800;color:var(--pm);border:1px solid var(--pm);border-radius:999px;padding:0 8px;margin-left:8px;vertical-align:middle}}
.bd p{{margin:.3em 0}} .bd .li{{margin:.15em 0 .15em .6em}} .bd .sp{{height:.5em}} .bd h3,.bd h4,.bd h5{{margin:.8em 0 .3em;line-height:1.3}} .bd h3{{font-size:19px}} .bd h4{{font-size:17px}} .bd h5{{font-size:15px}}
.bd table{{border-collapse:collapse;font-size:14px;margin:.5em 0;max-width:100%;display:block;overflow-x:auto}} .bd td{{border:1px solid var(--line);padding:5px 10px;vertical-align:top}} .bd tr:first-child td{{background:var(--panel);font-weight:700;color:var(--muted)}}
.bd pre{{background:#0a0c10;border:1px solid var(--line);border-radius:8px;padding:10px 12px;overflow-x:auto;font-size:13px}} .bd code{{background:rgba(255,255,255,.06);padding:0 .3em;border-radius:4px;font-size:.92em}}
.cp{{position:absolute;top:8px;right:8px;appearance:none;border:1px solid var(--line);background:var(--panel2);color:var(--text);font:inherit;font-size:12px;font-weight:700;padding:4px 10px;border-radius:8px;cursor:pointer}}
.muted{{color:var(--muted);font-weight:500}}
body.nothink .think{{display:none}} body.notool .tool,body.notool .tres{{display:none}} body.noside .side{{display:none}}
mark{{background:rgba(255,180,84,.35);color:inherit;padding:0 2px;border-radius:3px}}
</style></head><body>
<header><div><h1>{esc(title)}</h1><div class="sub">{esc(subtitle)}</div></div>
<div class="ctrl"><input type="search" id="q" placeholder="검색 (하이라이트)"><label><input type="checkbox" id="ck-think" checked> 생각</label><label><input type="checkbox" id="ck-tool" checked> 도구 호출</label><label><input type="checkbox" id="ck-side" checked> 서브에이전트</label></div>
<div class="rail"><button class="chip on" data-st="all">전체</button>{rail}</div></header>
<div class="layout"><aside><div class="stat">턴 {n_prompt} · 도구 호출 {n_tool:,} · 서브에이전트 이벤트 {n_side:,}<br><span class="muted">{esc(top_tools)}</span></div>{toc}</aside>
<main>{"".join(body)}</main></div>
<script>
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let st="all";
$$(".chip").forEach(c=>c.addEventListener("click",()=>{{st=c.dataset.st;$$(".chip").forEach(x=>x.classList.toggle("on",x===c));
  $$(".turn").forEach(t=>t.classList.toggle("hide",st!=="all"&&!t.dataset.stages.split(",").includes(st)));}}));
$("#ck-think").addEventListener("change",e=>document.body.classList.toggle("nothink",!e.target.checked));
$("#ck-tool").addEventListener("change",e=>document.body.classList.toggle("notool",!e.target.checked));
$("#ck-side").addEventListener("change",e=>document.body.classList.toggle("noside",!e.target.checked));
$$("[data-cp]").forEach(b=>b.addEventListener("click",async()=>{{const t=b.parentElement.querySelector(".bd").innerText;try{{await navigator.clipboard.writeText(t);b.textContent="복사됨 ✓"}}catch(e){{b.textContent="선택 후 ⌘C"}}setTimeout(()=>b.textContent="프롬프트 복사",1500)}}));
let orig=null;
$("#q").addEventListener("input",e=>{{const q=e.target.value.trim();const bds=$$(".bd, .tres pre");
  if(!orig){{orig=bds.map(b=>b.innerHTML)}} bds.forEach((b,i)=>{{b.innerHTML=orig[i]}});
  if(q.length<2)return;const re=new RegExp(q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,"\\\\$&"),"gi");
  bds.forEach(b=>{{const w=document.createTreeWalker(b,NodeFilter.SHOW_TEXT);const nodes=[];while(w.nextNode())nodes.push(w.currentNode);
    nodes.forEach(n=>{{if(!re.test(n.nodeValue))return;re.lastIndex=0;const span=document.createElement("span");span.innerHTML=n.nodeValue.replace(/[&<>]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;"}}[c])).replace(re,m=>"<mark>"+m+"</mark>");n.replaceWith(...span.childNodes)}})}})}});
</script></body></html>"""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("files",nargs="+")
    ap.add_argument("--title",required=True)
    ap.add_argument("--subtitle",default="")
    ap.add_argument("--out",required=True)
    ap.add_argument("--side-label",default="서브에이전트")
    a=ap.parse_args()
    recs=[]
    for i,p in enumerate(a.files): recs+=load(p,i)
    recs.sort(key=lambda r:(r["ts"] or ""))
    ev=flatten(recs)
    html_out=render(ev,a.title,a.subtitle,"메인",a.side_label)
    Path(a.out).write_text(html_out,encoding="utf-8")
    print(f"ok {a.out} ({len(html_out)//1024} KB) — 레코드 {len(recs)} · 이벤트 {len(ev)} · 파일 {len(a.files)}")

if __name__=="__main__": main()
