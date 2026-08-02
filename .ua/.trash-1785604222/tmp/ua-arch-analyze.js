#!/usr/bin/env node
'use strict';
// Structural analysis for architecture layer identification.
// Reads: input JSON { fileNodes, importEdges, allEdges }
// Writes: results JSON (see spec).

const fs = require('fs');
const path = require('path');

function main() {
  const inPath = process.argv[2];
  const outPath = process.argv[3];
  if (!inPath || !outPath) {
    console.error('Usage: ua-arch-analyze.js <input.json> <output.json>');
    process.exit(1);
  }
  const raw = JSON.parse(fs.readFileSync(inPath, 'utf8'));
  const fileNodes = raw.fileNodes || [];
  const importEdges = raw.importEdges || [];
  const allEdges = raw.allEdges || [];

  const nodeById = new Map();
  for (const n of fileNodes) nodeById.set(n.id, n);

  // ---------- A. Directory Grouping ----------
  // Compute common path prefix (directory-wise) across all filePaths.
  const paths = fileNodes.map(n => n.filePath || '').filter(Boolean);
  function segs(p) { return p.split(/[\\/]+/).filter(Boolean); }
  function commonPrefixDir(listOfSegLists) {
    if (!listOfSegLists.length) return [];
    let prefix = [];
    const first = listOfSegLists[0];
    for (let i = 0; i < first.length; i++) {
      const seg = first[i];
      // Only count directory segments as common prefix; stop when a segment is a file
      // (i.e., last segment of any path). We treat a segment as dir if ANY path has
      // further segments after it OR if it's not the last in its own path.
      let allHaveDir = true;
      for (const sl of listOfSegLists) {
        if (i >= sl.length) { allHaveDir = false; break; }
        if (sl[i] !== seg) { allHaveDir = false; break; }
        // segment is a "directory" only if it's not the final segment of this path
        if (i === sl.length - 1) { /* could be file */ }
      }
      if (!allHaveDir) break;
      // Only extend prefix while this segment is a directory for ALL paths
      // (i.e., every path has a segment after i). If some path ends here, stop.
      let allHaveMore = true;
      for (const sl of listOfSegLists) {
        if (i >= sl.length - 1) { allHaveMore = false; break; }
      }
      if (!allHaveMore) break;
      prefix.push(seg);
    }
    return prefix;
  }
  const segLists = paths.map(segs);
  const prefix = commonPrefixDir(segLists);
  const prefixStr = prefix.length ? prefix.join('/') + '/' : '';

  function groupOf(filePath) {
    if (!filePath) return '__root__';
    const s = segs(filePath);
    if (prefix.length && s.length > prefix.length) {
      // group by first segment AFTER prefix
      return s[prefix.length] || '__root__';
    }
    // no common prefix -> first segment or root
    if (s.length <= 1) return '__root__';
    return s[0];
  }

  const directoryGroups = {};
  for (const n of fileNodes) {
    const g = groupOf(n.filePath || '');
    if (!directoryGroups[g]) directoryGroups[g] = [];
    directoryGroups[g].push(n.id);
  }

  // ---------- B. Node Type Grouping ----------
  const nodeTypeGroups = {};
  for (const n of fileNodes) {
    if (!nodeTypeGroups[n.type]) nodeTypeGroups[n.type] = [];
    nodeTypeGroups[n.type].push(n.id);
  }

  // ---------- C. Import Adjacency (fan-in / fan-out) ----------
  const fanOut = {};
  const fanIn = {};
  for (const n of fileNodes) { fanOut[n.id] = 0; fanIn[n.id] = 0; }
  for (const e of importEdges) {
    if (fanOut[e.source] !== undefined) fanOut[e.source]++;
    if (fanIn[e.target] !== undefined) fanIn[e.target]++;
  }
  const fileFanIn = sortNumeric(fanIn);
  const fileFanOut = sortNumeric(fanOut);

  function sortNumeric(obj) {
    const arr = Object.entries(obj).filter(([k,v]) => v > 0);
    arr.sort((a,b) => b[1]-a[1]);
    const out = {};
    for (const [k,v] of arr) out[k] = v;
    return out;
  }

  // Reverse lookup: node id -> group
  const nodeToGroup = {};
  for (const [g, ids] of Object.entries(directoryGroups)) {
    for (const id of ids) nodeToGroup[id] = g;
  }

  // ---------- D. Cross-Category Dependency Analysis ----------
  const crossMap = {}; // "fromType|toType|edgeType" -> count
  for (const e of allEdges) {
    const s = nodeById.get(e.source);
    const t = nodeById.get(e.target);
    if (!s || !t) continue;
    const key = [s.type, t.type, e.type].join('|');
    crossMap[key] = (crossMap[key] || 0) + 1;
  }
  const crossCategoryEdges = Object.entries(crossMap).map(([k, count]) => {
    const [fromType, toType, edgeType] = k.split('|');
    return { fromType, toType, edgeType, count };
  }).sort((a,b) => b.count - a.count);

  // ---------- E. Inter-Group Import Frequency ----------
  const interMap = {}; // "from>to" -> count
  for (const e of importEdges) {
    const sg = nodeToGroup[e.source];
    const tg = nodeToGroup[e.target];
    if (!sg || !tg) continue;
    if (sg === tg) continue;
    const key = sg + '>' + tg;
    interMap[key] = (interMap[key] || 0) + 1;
  }
  const interGroupImports = Object.entries(interMap).map(([k, count]) => {
    const [from, to] = k.split('>');
    return { from, to, count };
  }).sort((a,b) => b.count - a.count);

  // ---------- F. Intra-Group Import Density ----------
  const intraGroupDensity = {};
  const groupEdgeTotal = {};
  const groupEdgeInternal = {};
  for (const g of Object.keys(directoryGroups)) { groupEdgeTotal[g] = 0; groupEdgeInternal[g] = 0; }
  for (const e of importEdges) {
    const sg = nodeToGroup[e.source];
    const tg = nodeToGroup[e.target];
    if (!sg || !tg) continue;
    groupEdgeTotal[sg]++; groupEdgeTotal[tg]++;
    if (sg === tg) groupEdgeInternal[sg]++;
  }
  for (const g of Object.keys(directoryGroups)) {
    const total = groupEdgeTotal[g];
    const internal = groupEdgeInternal[g];
    intraGroupDensity[g] = {
      internalEdges: internal,
      totalEdges: total,
      density: total > 0 ? +(internal / total).toFixed(3) : 0
    };
  }

  // ---------- G. Directory Pattern Matching ----------
  const dirPatterns = [
    [/^(routes?|api|controllers?|endpoints?|handlers?|routers?|serializers?|blueprints?)$/i, 'api'],
    [/^(services?|core|lib|domain|logic|internal|signals?|composables?|mailers?|jobs?|channels?)$/i, 'service'],
    [/^(models?|db|data|persistence|repository|entities?|migrations?|entity|sql|database|schema)$/i, 'data'],
    [/^(components?|views?|pages?|ui|layouts?|screens?)$/i, 'ui'],
    [/^(middleware|plugins?|interceptors?|guards?)$/i, 'middleware'],
    [/^(utils?|helpers?|common|shared|tools?|pkg|templatetags?)$/i, 'utility'],
    [/^(config|constants?|env|settings?|management|commands?)$/i, 'config'],
    [/^(__tests__|test|tests?|spec|specs?)$/i, 'test'],
    [/^(types?|interfaces?|schemas?|contracts?|dtos?|dto|request|response)$/i, 'types'],
    [/^(hooks?)$/i, 'hooks'],
    [/^(store|state|reducers?|actions?|slices?)$/i, 'state'],
    [/^(assets?|static|public)$/i, 'assets'],
    [/^(cmd|bin)$/i, 'entry'],
    [/^(docs?|documentation|wiki)$/i, 'documentation'],
    [/^(deploy|deployment|infra|infrastructure|docker|k8s|kubernetes|helm|charts?|terraform|tf)$/i, 'infrastructure'],
    [/^(\.github|\.gitlab|\.circleci)$/i, 'ci-cd'],
  ];

  const filePatterns = [
    [/(\.|^)(test|spec)\./i, 'test'],
    [/_test\.go$/i, 'test'],
    [/^test_.*\.py$/i, 'test'],
    [/Test\.java$/i, 'test'],
    [/_spec\.rb$/i, 'test'],
    [/Test\.php$/i, 'test'],
    [/Tests?\.cs$/i, 'test'],
    [/\.d\.ts$/i, 'types'],
    [/^(__init__|index)\.(py|ts|js|tsx|jsx)$/i, 'entry'],
    [/^manage\.py$/i, 'entry'],
    [/^wsgi\.py$|^asgi\.py$/i, 'config'],
    [/^main\.go$/i, 'entry'],
    [/^main\.rs$|^lib\.rs$/i, 'entry'],
    [/^Application\.java$|^Program\.cs$/i, 'entry'],
    [/^config\.ru$/i, 'entry'],
    [/^(Cargo\.toml|go\.mod|Gemfile|pom\.xml|build\.gradle|composer\.json|package\.json|pyproject\.toml|tsconfig\.json)/i, 'config'],
    [/^Dockerfile|^docker-compose/i, 'infrastructure'],
    [/\.tf$|\.tfvars$/i, 'infrastructure'],
    [/^Makefile$/i, 'infrastructure'],
    [/^\.github\/workflows\/|^\.gitlab-ci\.yml$|^Jenkinsfile/i, 'ci-cd'],
    [/\.sql$/i, 'data'],
    [/\.graphql$|\.gql$|\.proto$/i, 'types'],
    [/\.md$|\.rst$/i, 'documentation'],
  ];

  const patternMatches = {};
  for (const g of Object.keys(directoryGroups)) {
    let label = null;
    for (const [re, lab] of dirPatterns) { if (re.test(g)) { label = lab; break; } }
    patternMatches[g] = label;
  }

  // Per-file pattern (for nodes that don't fall in a matched directory)
  const filePatternMatches = {};
  for (const n of fileNodes) {
    let label = null;
    const base = n.name || '';
    for (const [re, lab] of filePatterns) {
      if (re.test(base) || re.test(n.filePath || '')) { label = lab; break; }
    }
    if (label) filePatternMatches[n.id] = label;
  }

  // ---------- H. Deployment Topology ----------
  const filePathList = fileNodes.map(n => n.filePath || '');
  const infraFiles = [];
  let hasDockerfile = false, hasCompose = false, hasK8s = false, hasTerraform = false, hasCI = false;
  for (const fp of filePathList) {
    if (/^Dockerfile/i.test(fp) || /\/Dockerfile/i.test(fp)) { hasDockerfile = true; infraFiles.push(fp); }
    if (/^docker-compose/i.test(fp) || /\/docker-compose/i.test(fp)) { hasCompose = true; infraFiles.push(fp); }
    if (/\.(ya?ml)$/.test(fp) && /k8s|kubernetes|manifest/i.test(fp)) { hasK8s = true; infraFiles.push(fp); }
    if (/\.tf$|\.tfvars$/.test(fp)) { hasTerraform = true; infraFiles.push(fp); }
    if (/^\.github\/workflows\//.test(fp) || /\.gitlab-ci\.yml$/.test(fp) || /Jenkinsfile/.test(fp)) { hasCI = true; infraFiles.push(fp); }
    if (/^Makefile$/.test(fp)) { infraFiles.push(fp); }
  }
  const deploymentTopology = {
    hasDockerfile, hasCompose, hasK8s, hasTerraform, hasCI,
    infraFiles: unique(infraFiles)
  };

  // ---------- I. Data Pipeline Detection ----------
  const schemaFiles = [];
  const migrationFiles = [];
  const dataModelFiles = [];
  const apiHandlerFiles = [];
  for (const n of fileNodes) {
    const fp = n.filePath || '';
    if (/\.(sql|graphql|gql|proto|prisma)$/.test(fp) || n.type === 'schema' || n.type === 'table') {
      if (/migrat/i.test(fp)) migrationFiles.push(fp);
      else schemaFiles.push(fp);
    }
    if (/models?\//.test(fp) || /\/(models?|entities?|repository)\./.test(fp) || /\b(model|entity)\b/i.test((n.tags||[]).join(','))) {
      dataModelFiles.push(fp);
    }
    if (/(routes?|controllers?|api|endpoints?)\//.test(fp) || n.type === 'endpoint' || /\bendpoint\b/i.test((n.tags||[]).join(','))) {
      apiHandlerFiles.push(fp);
    }
  }
  const dataPipeline = {
    schemaFiles: unique(schemaFiles),
    migrationFiles: unique(migrationFiles),
    dataModelFiles: unique(dataModelFiles),
    apiHandlerFiles: unique(apiHandlerFiles)
  };

  // ---------- J. Documentation Coverage ----------
  const docFilePaths = new Set(fileNodes.filter(n => n.type === 'document').map(n => n.filePath || ''));
  let groupsWithDocs = 0;
  const undocumentedGroups = [];
  for (const [g, ids] of Object.entries(directoryGroups)) {
    const hasDoc = ids.some(id => {
      const n = nodeById.get(id);
      return n && n.type === 'document';
    });
    if (hasDoc) groupsWithDocs++;
    else undocumentedGroups.push(g);
  }
  const totalGroups = Object.keys(directoryGroups).length;
  const docCoverage = {
    groupsWithDocs,
    totalGroups,
    coverageRatio: totalGroups ? +(groupsWithDocs / totalGroups).toFixed(2) : 0,
    undocumentedGroups
  };

  // ---------- K. Dependency Direction ----------
  // Aggregate inter-group imports: A depends on B if A->B count > B->A count.
  const pairCount = {}; // "A|B" -> net toward A
  for (const { from, to, count } of interGroupImports) {
    const f = [from, to].sort().join('|');
    if (!pairCount[f]) pairCount[f] = { a: from < to ? from : to, b: from < to ? to : from, ab: 0, ba: 0 };
    const pc = pairCount[f];
    if (from === pc.a) pc.ab += count; else pc.ba += count;
  }
  const dependencyDirection = [];
  for (const k of Object.keys(pairCount)) {
    const pc = pairCount[k];
    if (pc.ab > pc.ba) dependencyDirection.push({ dependent: pc.a, dependsOn: pc.b, diff: pc.ab - pc.ba });
    else if (pc.ba > pc.ab) dependencyDirection.push({ dependent: pc.b, dependsOn: pc.a, diff: pc.ba - pc.ab });
  }
  dependencyDirection.sort((a,b) => b.diff - a.diff);

  // ---------- File stats ----------
  const filesPerGroup = {};
  for (const [g, ids] of Object.entries(directoryGroups)) filesPerGroup[g] = ids.length;
  const nodeTypeCounts = {};
  for (const [t, ids] of Object.entries(nodeTypeGroups)) nodeTypeCounts[t] = ids.length;
  const fileStats = {
    totalFileNodes: fileNodes.length,
    filesPerGroup,
    nodeTypeCounts
  };

  const results = {
    scriptCompleted: true,
    commonPrefix: prefixStr,
    directoryGroups,
    nodeTypeGroups,
    crossCategoryEdges,
    interGroupImports,
    intraGroupDensity,
    patternMatches,
    filePatternMatches,
    deploymentTopology,
    dataPipeline,
    docCoverage,
    dependencyDirection,
    fileStats,
    fileFanIn,
    fileFanOut
  };

  fs.writeFileSync(outPath, JSON.stringify(results, null, 2));
  console.log('OK: wrote ' + outPath);
}

function unique(arr) {
  return Array.from(new Set(arr));
}

main();
