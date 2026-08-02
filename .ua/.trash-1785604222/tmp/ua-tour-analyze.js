#!/usr/bin/env node
/* eslint-disable */
// Tour topology analyzer for the Understand-Anything tour builder.
// Computes fan-in/out, entry points, BFS dependency traversal, non-code
// inventory, coupled clusters, layers, and a node summary index.
'use strict';

const fs = require('fs');

function die(msg) {
  process.stderr.write('FATAL: ' + msg + '\n');
  process.exit(1);
}

const inputPath = process.argv[2];
const outPath = process.argv[3];
if (!inputPath || !outPath) {
  die('usage: ua-tour-analyze.js <input.json> <output.json>');
}

let data;
try {
  data = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
} catch (e) {
  die('cannot read/parse input: ' + e.message);
}

const nodes = Array.isArray(data.nodes) ? data.nodes : [];
const edges = Array.isArray(data.edges) ? data.edges : [];
const layers = Array.isArray(data.layers) ? data.layers : [];

const nodeById = new Map();
for (const n of nodes) nodeById.set(n.id, n);

// ---- A & B: fan-in / fan-out ----
const fanIn = new Map();
const fanOut = new Map();
for (const n of nodes) { fanIn.set(n.id, 0); fanOut.set(n.id, 0); }
for (const e of edges) {
  if (fanIn.has(e.target)) fanIn.set(e.target, fanIn.get(e.target) + 1);
  if (fanOut.has(e.source)) fanOut.set(e.source, fanOut.get(e.source) + 1);
}
const fanInRanking = nodes
  .map(n => ({ id: n.id, fanIn: fanIn.get(n.id), name: n.name }))
  .sort((a, b) => b.fanIn - a.fanIn)
  .slice(0, 20);
const fanOutRanking = nodes
  .map(n => ({ id: n.id, fanOut: fanOut.get(n.id), name: n.name }))
  .sort((a, b) => b.fanOut - a.fanOut)
  .slice(0, 20);

// ---- C: entry point candidates ----
const ENTRY_NAMES = new Set([
  'index.ts','index.js','main.ts','main.js','app.ts','app.js','server.ts','server.js',
  'mod.rs','main.go','main.py','main.rs','manage.py','app.py','wsgi.py','asgi.py',
  'run.py','__main__.py','Application.java','Main.java','Program.cs','config.ru',
  'index.php','App.swift','Application.kt','main.cpp','main.c'
]);
const fanOutVals = nodes.map(n => fanOut.get(n.id)).sort((a, b) => b - a);
const fanInVals = nodes.map(n => fanIn.get(n.id)).sort((a, b) => a - b);
const top10pctFanOutThreshold = fanOutVals[Math.floor(fanOutVals.length * 0.10)] || 0;
const bottom25pctFanInThreshold = fanInVals[Math.floor(fanInVals.length * 0.25)] || 0;

function depthOf(filePath) {
  if (!filePath) return 99;
  const parts = filePath.replace(/\\/g, '/').split('/').filter(Boolean);
  return parts.length;
}

const entryCandidates = nodes.map(n => {
  let score = 0;
  const isDoc = n.type === 'document';
  if (!isDoc) {
    if (ENTRY_NAMES.has(n.name)) score += 3;
    if (depthOf(n.filePath) <= 2) score += 1;
    if (fanOut.get(n.id) >= top10pctFanOutThreshold && top10pctFanOutThreshold > 0) score += 1;
    if (fanIn.get(n.id) <= bottom25pctFanInThreshold) score += 1;
  } else {
    if (n.filePath === 'README.md' || n.name === 'README.md') score += 5;
    else if (depthOf(n.filePath) <= 1) score += 2;
  }
  return { id: n.id, score, name: n.name, type: n.type, summary: n.summary || '' };
}).sort((a, b) => b.score - a.score);
const entryPointCandidates = entryCandidates.slice(0, 5);

// ---- D: BFS from top CODE entry point ----
const topCodeEntry = entryCandidates.find(c => c.type !== 'document' && nodeById.has(c.id));
const bfsTraversal = { startNode: null, order: [], depthMap: {}, byDepth: {} };
if (topCodeEntry) {
  const start = topCodeEntry.id;
  bfsTraversal.startNode = start;
  const adj = new Map();
  for (const n of nodes) adj.set(n.id, []);
  for (const e of edges) {
    if (e.type === 'imports' || e.type === 'calls') {
      if (adj.has(e.source)) adj.get(e.source).push(e.target);
    }
  }
  const visited = new Set([start]);
  const queue = [{ id: start, depth: 0 }];
  bfsTraversal.depthMap[start] = 0;
  bfsTraversal.order.push(start);
  while (queue.length) {
    const cur = queue.shift();
    for (const nb of (adj.get(cur.id) || [])) {
      if (!visited.has(nb)) {
        visited.add(nb);
        const d = cur.depth + 1;
        bfsTraversal.depthMap[nb] = d;
        bfsTraversal.order.push(nb);
        queue.push({ id: nb, depth: d });
      }
    }
  }
  for (const [id, d] of Object.entries(bfsTraversal.depthMap)) {
    const k = String(d);
    (bfsTraversal.byDepth[k] = bfsTraversal.byDepth[k] || []).push(id);
  }
}

// ---- E: non-code inventory ----
const nonCodeFiles = { documentation: [], infrastructure: [], data: [], config: [] };
const catMap = {
  document: 'documentation',
  service: 'infrastructure', pipeline: 'infrastructure', resource: 'infrastructure',
  table: 'data', schema: 'data', endpoint: 'data',
  config: 'config'
};
for (const n of nodes) {
  const cat = catMap[n.type];
  if (cat) nonCodeFiles[cat].push({ id: n.id, name: n.name, type: n.type, summary: n.summary || '' });
}

// ---- F: tightly coupled clusters ----
// bidirectional pairs across imports/calls, then expand.
const dirEdges = new Set();
for (const e of edges) {
  if (e.type === 'imports' || e.type === 'calls' || e.type === 'depends_on') {
    dirEdges.add(e.source + '||' + e.target);
  }
}
const pairs = [];
for (const k of dirEdges) {
  const [a, b] = k.split('||');
  if (dirEdges.has(b + '||' + a)) pairs.push([a, b]);
}
// adjacency for cluster expansion
const nbrs = new Map();
for (const n of nodes) nbrs.set(n.id, new Set());
for (const e of edges) {
  if (e.type === 'imports' || e.type === 'calls' || e.type === 'depends_on') {
    if (nbrs.has(e.source)) nbrs.get(e.source).add(e.target);
    if (nbrs.has(e.target)) nbrs.get(e.target).add(e.source);
  }
}
function edgeCountWithin(set) {
  let c = 0;
  for (const e of edges) {
    if (e.type === 'imports' || e.type === 'calls' || e.type === 'depends_on') {
      if (set.has(e.source) && set.has(e.target)) c++;
    }
  }
  return c;
}
const clusterSet = new Set(); // dedupe by sorted member key
const clusters = [];
for (const [a, b] of pairs) {
  const members = new Set([a, b]);
  // expand: add nodes connected to >=2 existing members
  let changed = true;
  while (changed && members.size < 5) {
    changed = false;
    for (const n of nodes) {
      if (members.has(n.id)) continue;
      const ns = nbrs.get(n.id) || new Set();
      let cnt = 0;
      for (const m of members) if (ns.has(m)) cnt++;
      if (cnt >= 2) { members.add(n.id); changed = true; if (members.size >= 5) break; }
    }
  }
  const key = [...members].sort().join('|');
  if (clusterSet.has(key)) continue;
  clusterSet.add(key);
  const ec = edgeCountWithin(members);
  clusters.push({ nodes: [...members], edgeCount: ec, size: members.size });
}
clusters.sort((a, b) => b.edgeCount - a.edgeCount || b.size - a.size);
const topClusters = clusters.slice(0, 10);

// ---- G: layers ----
const layerOut = {
  count: layers.length,
  list: layers.map(l => ({ id: l.id, name: l.name, description: l.description }))
};

// ---- H: node summary index ----
const nodeSummaryIndex = {};
for (const n of nodes) {
  nodeSummaryIndex[n.id] = { name: n.name, type: n.type, summary: n.summary || '' };
}

const result = {
  scriptCompleted: true,
  entryPointCandidates,
  fanInRanking,
  fanOutRanking,
  bfsTraversal,
  nonCodeFiles,
  clusters: topClusters,
  layers: layerOut,
  nodeSummaryIndex,
  totalNodes: nodes.length,
  totalEdges: edges.length
};

try {
  fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
} catch (e) {
  die('cannot write output: ' + e.message);
}
console.log('OK: ' + nodes.length + ' nodes, ' + edges.length + ' edges; wrote ' + outPath);
process.exit(0);
