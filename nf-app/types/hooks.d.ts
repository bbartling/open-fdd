// Browser-page globals that static/sparql.js reads behind `typeof x !== "undefined"` guards;
// in the hooks program (where sparql.js is loaded through require) they do not exist.
declare const rdf: any;
declare const model: any;
declare function modelToTurtle(m: any, base: string, opts?: any): { turtle: string };
