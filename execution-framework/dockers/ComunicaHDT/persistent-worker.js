"use strict";

const readline = require("node:readline");
const { QueryEngine } = require("@comunica/query-sparql-hdt");
const { ActionContext } = require("@comunica/core");
const { KeysInitQuery, KeysQueryOperation } = require("@comunica/context-entries");

const artifact = process.argv[2];
if (!artifact || !artifact.startsWith("/") || !artifact.endsWith(".hdt")) {
  throw new Error("one absolute HDT artifact is required");
}

const engine = new QueryEngine();
let identifiedSource = null;
let context = null;
const write = value => process.stdout.write(`${JSON.stringify(value)}\n`);

function findUnique(root, predicate, label) {
  const found = [];
  const seen = new Set();
  const queue = [root];
  while (queue.length > 0) {
    const value = queue.shift();
    if (!value || (typeof value !== "object" && typeof value !== "function")
        || seen.has(value)) continue;
    seen.add(value);
    if (predicate(value)) found.push(value);
    for (const key of Object.keys(value)) {
      if (["map", "cachedActors", "testCache", "_events"].includes(key)) continue;
      const child = value[key];
      if (child && (typeof child === "object" || typeof child === "function")) {
        queue.push(child);
      }
    }
  }
  if (found.length !== 1) {
    throw new Error(`expected one ${label}, found ${found.length}`);
  }
  return found[0];
}

async function openIdentifiedSource() {
  const actorInitQuery = engine.actorInitQuery;
  if (!actorInitQuery) throw new Error("engine.actorInitQuery is unavailable");
  const queryProcessor = findUnique(actorInitQuery, value =>
    value?.constructor?.name === "ActorQueryProcessSequential"
      && value.mediatorContextPreprocess && value.mediatorOptimizeQueryOperation,
  "sequential query processor");
  const sourceIdentifier = findUnique(actorInitQuery, value =>
    value?.constructor?.name === "ActorOptimizeQueryOperationQuerySourceIdentify"
      && typeof value.identifySource === "function"
      && value.mediatorQuerySourceIdentify,
  "query source identifier");
  const preprocessed = await queryProcessor.mediatorContextPreprocess.mediate({
    context: new ActionContext(),
    initialize: true,
  });
  if (!preprocessed.context.has(KeysInitQuery.dataFactory)) {
    throw new Error("context preprocessing omitted dataFactory");
  }
  identifiedSource = await sourceIdentifier.identifySource(
    { type: "hdt", value: artifact }, preprocessed.context);
  if (!identifiedSource?.source
      || identifiedSource.source.constructor?.name !== "QuerySourceHdt"
      || identifiedSource.source.referenceValue !== artifact) {
    throw new Error("HDT source identification returned an invalid source");
  }
  context = preprocessed.context
    .delete(KeysInitQuery.querySourcesUnidentified)
    .set(KeysQueryOperation.querySources, [identifiedSource]);
}

async function closeIdentifiedSource() {
  const source = identifiedSource?.source;
  identifiedSource = null;
  context = null;
  if (source && typeof source.dispose === "function") await source.dispose();
}

function term(value) {
  if (value === undefined) return null;
  if (value.termType === "NamedNode") {
    return { type: "uri", value: value.value };
  }
  if (value.termType === "BlankNode") {
    return { type: "bnode", value: value.value };
  }
  if (value.termType === "Literal") {
    return {
      type: "literal",
      value: value.value,
      language: value.language || null,
      datatype: value.datatype ? value.datatype.value : null,
    };
  }
  throw new Error(`unsupported RDF term: ${value.termType}`);
}

function withoutComments(query) {
  let output = "";
  let iri = false;
  let quote = null;
  let escaped = false;
  for (let index = 0; index < query.length; index += 1) {
    const character = query[index];
    if (escaped) { output += character; escaped = false; continue; }
    if (quote && character === "\\") { output += character; escaped = true; continue; }
    if (!quote && character === "<") { iri = true; output += character; continue; }
    if (!quote && character === ">") { iri = false; output += character; continue; }
    if (!iri && (character === "\"" || character === "'")) {
      quote = quote === character ? null : (quote || character);
      output += character;
      continue;
    }
    if (!iri && !quote && character === "#") {
      while (index + 1 < query.length && !"\r\n".includes(query[index + 1])) index += 1;
      output += " ";
      continue;
    }
    output += character;
  }
  return output;
}

function queryForm(query) {
  const match = withoutComments(query).match(/\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b/i);
  if (!match) throw new Error("unsupported or unrecognized SPARQL query form");
  return match[1].toUpperCase();
}

function projectedVariables(query) {
  const clean = withoutComments(query);
  const match = clean.match(/\bSELECT\b(?:\s+(?:DISTINCT|REDUCED))?([\s\S]*?)\bWHERE\b/i);
  if (!match || /(^|\s)\*(?=\s|$)/.test(match[1])) return [];
  const values = [];
  const seen = new Set();
  for (const variable of match[1].matchAll(/[?$]([A-Za-z_][A-Za-z0-9_]*)/g)) {
    if (!seen.has(variable[1])) { seen.add(variable[1]); values.push(variable[1]); }
  }
  return values;
}

async function select(query) {
  const stream = await engine.queryBindings(query, context);
  const metadata = await stream.getProperty("metadata", { optional: true });
  const variables = metadata?.variables?.map(variable => variable.value) || [];
  const bindings = await stream.toArray();
  const declaredVariables = projectedVariables(query);
  const effectiveVariables = declaredVariables.length > 0
    ? declaredVariables
    : (variables.length > 0 ? variables : [ ...new Set(bindings.flatMap(binding =>
        [ ...binding.keys() ].map(variable => variable.value))) ]);
  const rows = bindings.map(binding => Object.fromEntries(
    effectiveVariables.flatMap(variable => {
      const value = binding.get(variable);
      return value === undefined ? [] : [ [ variable, term(value) ] ];
    }),
  ));
  return { kind: "select", variables: effectiveVariables, rows };
}

async function graph(query) {
  const stream = await engine.queryQuads(query, context);
  const quads = await stream.toArray();
  return {
    kind: "graph",
    triples: quads.map(quad => [
      term(quad.subject), term(quad.predicate), term(quad.object),
    ]),
  };
}

async function materialize(query) {
  const form = queryForm(query);
  if (form === "SELECT") return select(query);
  if (form === "ASK") {
    return { kind: "ask", boolean: await engine.queryBoolean(query, context) };
  }
  return graph(query);
}

async function handle(request) {
  if (request.kind === "shutdown") {
    await closeIdentifiedSource();
    write({ kind: "stopped" });
    process.exit(0);
  }
  if (request.kind !== "query"
      || !Number.isInteger(request.request_id)
      || typeof request.query !== "string") {
    throw new Error("invalid jsonl-v1 request");
  }
  const document = await materialize(request.query);
  write({
    kind: "result",
    request_id: request.request_id,
    status: "ok",
    document,
  });
}

const input = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
});
let chain = Promise.resolve();
input.on("line", line => {
  chain = chain.then(async () => {
    let request;
    try {
      request = JSON.parse(line);
      await handle(request);
    } catch (error) {
      write({
        kind: "result",
        request_id: request?.request_id ?? null,
        status: "error",
        error_type: error.name,
        error_message: error.message,
      });
    }
  });
});
openIdentifiedSource().then(() => {
  write({
    kind: "ready",
    protocol: "jsonl-v1",
    source_open: true,
    source_type: "hdt",
    source_boundary: "comunica-query-source-identify",
    source_reference: artifact,
  });
}).catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exit(1);
});
