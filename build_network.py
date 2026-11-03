"""Build the NVIDIA ecosystem graph with NetworkX, analyze it, and export
JSON (for the interactive page) plus a static PNG.

usage: python3 build_network.py <data_dir> <out_dir>
"""
import sys, csv, json, math
from collections import Counter, defaultdict
import networkx as nx

data_dir, out_dir = sys.argv[1], sys.argv[2]

def read(name):
    with open(f"{data_dir}/{name}", newline="") as f:
        return list(csv.DictReader(f))

nodes = {r["id"]: r for r in read("nodes.csv")}
sources = {r["key"]: r for r in read("sources.csv")}
edges = read("edges.csv")

# ---------- graph ----------
G = nx.MultiDiGraph()
for n, r in nodes.items():
    G.add_node(n, category=r["category"], country=r["country"])
for e in edges:
    for end in (e["source"], e["target"]):
        if end not in nodes:
            raise SystemExit(f"edge endpoint missing from nodes.csv: {end}")
    if e["src"] not in sources:
        raise SystemExit(f"unknown source key: {e['src']}")
    G.add_edge(e["source"], e["target"], type=e["type"], detail=e["detail"],
               date=e["date"], src=e["src"])

isolated = [n for n in G if G.degree(n) == 0]
if isolated:
    raise SystemExit(f"isolated nodes: {isolated}")

U = nx.Graph(G)                      # simple undirected view
H = U.copy(); H.remove_node("NVIDIA")  # NVIDIA is the hub by construction
H.remove_nodes_from([n for n in list(H) if nodes[n]["category"] == "Person"])
H.remove_nodes_from(list(nx.isolates(H)))

# ---------- analysis ----------
type_counts = Counter(d["type"] for *_, d in G.edges(data=True))
cat_counts = Counter(r["category"] for r in nodes.values())

betw = nx.betweenness_centrality(H)
deg_all = dict(U.degree())
pagerank = nx.pagerank(nx.DiGraph(G))

comms = nx.community.louvain_communities(H, seed=42, resolution=1.0)
comms = sorted(comms, key=len, reverse=True)
comm_of = {n: i for i, c in enumerate(comms) for n in c}

# relationship types each node has with NVIDIA (either direction)
rel = defaultdict(set)
for u, v, d in G.edges(data=True):
    if u == "NVIDIA": rel[v].add(d["type"])
    elif v == "NVIDIA": rel[u].add(d["type"])

circular = sorted(n for n, t in rel.items() if "investment" in t and "customer" in t)
invests_in_supplier = sorted(n for n, t in rel.items() if "investment" in t and "supplier" in t)
frenemies = sorted(n for n, t in rel.items() if "competitor" in t and len(t) > 1)
multi = sorted(((n, sorted(t)) for n, t in rel.items() if len(t) >= 2), key=lambda x: -len(x[1]))

# companies linked to NVIDIA only through others (2 hops away)
direct = set(rel)
two_hop = sorted(n for n in G if n != "NVIDIA" and n not in direct)

core = nx.core_number(H)
kmax = max(core.values())
inner_core = sorted(n for n, k in core.items() if k == kmax)

top_betw = sorted(betw.items(), key=lambda x: -x[1])[:10]
top_deg = sorted(((n, d) for n, d in deg_all.items() if n != "NVIDIA"), key=lambda x: -x[1])[:10]

def label_comm(c):
    cats = Counter(nodes[n]["category"] for n in c)
    hub = max(c, key=lambda n: deg_all[n])
    return f"{hub} cluster", cats.most_common(1)[0][0]

communities_out = []
for i, c in enumerate(comms):
    if len(c) < 3: continue
    name, cat = label_comm(c)
    communities_out.append({"id": i, "name": name, "size": len(c),
                            "members": sorted(c, key=lambda n: -deg_all[n])})

print(f"{G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
print("edge types:", dict(type_counts))
print("top betweenness (NVIDIA & people removed):", [(n, round(b, 3)) for n, b in top_betw[:6]])
print("top degree:", top_deg[:6])
print("circular (invests AND sells to):", circular)
print("invests in supplier:", invests_in_supplier)
print("frenemies (competitor + another tie):", frenemies)
print("multi-tie:", multi[:8])
print(f"{kmax}-core:", inner_core)
print("communities >=3:", [(c['name'], c['size']) for c in communities_out])
print("not directly tied to NVIDIA:", two_hop)

# ---------- layout: categories in sectors around NVIDIA, then spring ----------
order = ["AI lab", "Big tech", "AI cloud", "Sovereign AI", "Telecom", "Enterprise software",
         "Health & science", "Quantum", "Robotics", "Mobility", "Power & cooling",
         "Servers", "Supply chain", "Chips", "Acquired by NVIDIA", "Regulator", "Person"]
members = defaultdict(list)
for n, r in nodes.items():
    if n != "NVIDIA": members[r["category"]].append(n)
total = sum(len(v) for v in members.values())
pos, angle = {"NVIDIA": (0.0, 0.0)}, 0.0
gap = 0.035                       # radians of empty space between sectors
outer = set(two_hop)
counted = {c: [n for n in members[c] if n not in outer] for c in order}
total = sum(len(v) for v in counted.values())
avail = 2 * math.pi - gap * len(order)
rings = [0.42, 0.60, 0.78, 0.96]
for cat in order:
    ms = sorted(counted[cat], key=lambda n: -deg_all[n])
    if not ms: continue
    span = avail * len(ms) / total
    for i, n in enumerate(ms):
        a = angle + span * (i + 0.5) / len(ms)
        r = rings[i % len(rings)] if len(ms) > 3 else rings[1 + i % 2]
        if deg_all[n] >= 6: r = 0.30 + 0.14 * (i % 2)   # big hubs sit nearer the centre, staggered
        pos[n] = (r * math.cos(a), r * math.sin(a))
    angle += span + gap
for n in outer:                   # 2-hop nodes sit just outside their neighbour
    nb = next(iter(U[n]))
    x, y = pos[nb]; a = math.atan2(y, x)
    pos[n] = (1.12 * math.cos(a + 0.02), 1.12 * math.sin(a + 0.02))
pos = {n: (float(x), float(y)) for n, (x, y) in pos.items()}

# ---------- export ----------
cat_list = [c for c in order if c in cat_counts]
out = {
    "generated": "2026-10-29",
    "stats": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
              "types": dict(type_counts), "categories": {c: cat_counts[c] for c in cat_list},
              "direct": len(direct), "sources": len(sources)},
    "categories": cat_list,
    "nodes": [{"id": n, "category": nodes[n]["category"], "country": nodes[n]["country"],
               "x": round(float(pos[n][0]), 4), "y": round(float(pos[n][1]), 4),
               "degree": deg_all[n], "betweenness": round(betw.get(n, 0), 4),
               "pagerank": round(pagerank[n], 4), "community": comm_of.get(n, -1),
               "nvidia_ties": sorted(rel.get(n, []))} for n in G],
    "edges": [{"s": u, "t": v, "type": d["type"], "detail": d["detail"], "date": d["date"],
               "src": d["src"]} for u, v, d in G.edges(data=True)],
    "sources": {k: {"title": s["title"], "url": s["url"]} for k, s in sources.items()},
    "insights": {
        "top_betweenness": [[n, round(b, 3)] for n, b in top_betw],
        "top_degree": top_deg,
        "circular": circular,
        "invests_in_supplier": invests_in_supplier,
        "frenemies": frenemies,
        "multi": multi,
        "inner_core": {"k": kmax, "members": inner_core},
        "communities": communities_out,
        "two_hop": two_hop,
    },
}
with open(f"{out_dir}/nvidia_graph.json", "w") as f:
    json.dump(out, f)
nx.write_graphml(nx.DiGraph(G), f"{out_dir}/nvidia_graph.graphml")

# ---------- static PNG ----------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

edge_col = {"investment": "#1D9E75", "acquisition": "#7F77DD", "supplier": "#EF9F27",
            "customer": "#378ADD", "partner": "#8A8F98", "competitor": "#E24B4A",
            "regulator": "#B5651D", "leadership": "#C9C5BB", "ecosystem": "#C9C5BB"}
cat_col = dict(zip(cat_list, plt.cm.tab20.colors))
fig, ax = plt.subplots(figsize=(22, 22))
for t, c in edge_col.items():
    es = [(u, v) for u, v, d in G.edges(data=True) if d["type"] == t]
    nx.draw_networkx_edges(G, pos, edgelist=es, edge_color=c, alpha=0.35 if t in ("partner", "ecosystem", "leadership") else 0.6,
                           width=0.8, arrows=False, ax=ax)
sizes = [3000 if n == "NVIDIA" else 60 + 28 * deg_all[n] for n in G]
nx.draw_networkx_nodes(G, pos, node_size=sizes, ax=ax, linewidths=0.6, edgecolors="#333",
                       node_color=["#76B900" if n == "NVIDIA" else cat_col[nodes[n]["category"]] for n in G])
nx.draw_networkx_labels(G, pos, font_size=7, ax=ax)
ax.legend(handles=[Patch(color=cat_col[c], label=c) for c in cat_list] +
          [Line2D([0], [0], color=c, lw=3, label=t) for t, c in edge_col.items() if t not in ("leadership",)],
          loc="lower left", fontsize=10, ncol=2, frameon=False)
ax.set_title(f"NVIDIA ecosystem — {G.number_of_nodes()} organizations & people, {G.number_of_edges()} sourced relationships (Oct 2026)", fontsize=16)
ax.axis("off"); plt.tight_layout()
plt.savefig(f"{out_dir}/nvidia_network_full.png", dpi=110)
