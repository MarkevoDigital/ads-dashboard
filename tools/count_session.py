"""Conta mensagens, interacoes e intervalo de tempo nos transcritos da sessao."""
import json
import os
from datetime import datetime

FILES = [
    r"C:\Users\User\.claude\projects\C--Users-User-OneDrive-Documentos-Claude\a4acaaaf-0e04-4901-a334-cd0fe02a5f00.jsonl",
    r"C:\Users\User\.claude\projects\C--Users-User-OneDrive-Documentos-Claude\191a4e8c-6dfc-49b3-8183-629ba28ba8e3.jsonl",
]


def _parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


tot = dict(lines=0, user_msgs=0, assistant_msgs=0, tool_use=0, tool_result=0)
ts_min = ts_max = None
all_ts = []
days = set()

for path in FILES:
    if not os.path.exists(path):
        continue
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        tot["lines"] += 1
        ts = _parse_ts(o.get("timestamp", "")) if isinstance(o.get("timestamp"), str) else None
        if ts:
            ts_min = ts if ts_min is None or ts < ts_min else ts_min
            ts_max = ts if ts_max is None or ts > ts_max else ts_max
            all_ts.append(ts)
            days.add(ts.date())
        msg = o.get("message") or {}
        content = msg.get("content")
        blocks = content if isinstance(content, list) else (
            [{"type": "text"}] if isinstance(content, str) else [])
        types = [b.get("type") for b in blocks if isinstance(b, dict)]
        t = o.get("type")
        if t == "assistant":
            tot["assistant_msgs"] += 1
            tot["tool_use"] += types.count("tool_use")
        elif t == "user":
            tot["tool_result"] += types.count("tool_result")
            # prompt real do usuario = bloco de texto sem tool_result
            if ("tool_result" not in types) and (("text" in types) or isinstance(content, str)):
                tot["user_msgs"] += 1

print("=== TOTAIS (todas as sessoes deste projeto) ===")
for k, v in tot.items():
    print(f"  {k}: {v}")
if ts_min and ts_max:
    span = ts_max - ts_min
    h = span.total_seconds() / 3600
    print(f"  primeiro evento: {ts_min}")
    print(f"  ultimo evento:   {ts_max}")
    print(f"  intervalo (calendario): {span.days}d {span.seconds//3600}h {(span.seconds%3600)//60}m  (= {h:.1f} horas)")
    all_ts.sort()
    GAP = 30 * 60  # pausa = gap > 30 min
    active = 0.0
    for a, b in zip(all_ts, all_ts[1:]):
        d = (b - a).total_seconds()
        if d <= GAP:
            active += d
    print(f"  tempo ATIVO estimado (gaps<=30min): {active/3600:.1f} horas")
    print(f"  dias distintos com atividade: {len(days)} -> {sorted(str(d) for d in days)}")
