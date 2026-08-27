"use strict";

const readline = require("node:readline");
const { QueryEngine } = require("@comunica/query-sparql-hdt");

const artifact = process.argv[2];
if (!artifact || !artifact.startsWith("/") || !artifact.endsWith(".hdt")) {
  throw new Error("one absolute HDT artifact is required");
}

const engine = new QueryEngine();
const context = {
  sources: [
    {
      type: "hdt",
      value: artifact,
    },
  ],
};
const write = value => process.stdout.write(`${JSON.stringify(value)}\n`);

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
write({ kind: "ready", protocol: "jsonl-v1" });
