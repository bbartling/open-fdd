/* @ts-self-types="./web.d.ts" */

class AsyncParserIterator {
    static __wrap(ptr) {
        const obj = Object.create(AsyncParserIterator.prototype);
        obj.__wbg_ptr = ptr;
        AsyncParserIteratorFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        AsyncParserIteratorFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_asyncparseriterator_free(ptr, 0);
    }
    /**
     * @returns {Promise<ParserIteratorResult>}
     */
    next() {
        const ret = wasm.asyncparseriterator_next(this.__wbg_ptr);
        return ret;
    }
}
if (Symbol.dispose) AsyncParserIterator.prototype[Symbol.dispose] = AsyncParserIterator.prototype.free;

export class BlankNode {
    static __wrap(ptr) {
        const obj = Object.create(BlankNode.prototype);
        obj.__wbg_ptr = ptr;
        BlankNodeFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        BlankNodeFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_blanknode_free(ptr, 0);
    }
    /**
     * @param {any} other
     * @returns {boolean}
     */
    equals(other) {
        const ret = wasm.blanknode_equals(this.__wbg_ptr, other);
        return ret !== 0;
    }
    /**
     * @returns {string}
     */
    get termType() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.blanknode_term_type(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    toString() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.blanknode_toString(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get value() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.blanknode_value(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) BlankNode.prototype[Symbol.dispose] = BlankNode.prototype.free;

export class DefaultGraph {
    static __wrap(ptr) {
        const obj = Object.create(DefaultGraph.prototype);
        obj.__wbg_ptr = ptr;
        DefaultGraphFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        DefaultGraphFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_defaultgraph_free(ptr, 0);
    }
    /**
     * @param {any} other
     * @returns {boolean}
     */
    equals(other) {
        const ret = wasm.defaultgraph_equals(this.__wbg_ptr, other);
        return ret !== 0;
    }
    /**
     * @returns {string}
     */
    get termType() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.defaultgraph_term_type(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    toString() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.defaultgraph_toString(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get value() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.defaultgraph_value(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) DefaultGraph.prototype[Symbol.dispose] = DefaultGraph.prototype.free;

export class Literal {
    static __wrap(ptr) {
        const obj = Object.create(Literal.prototype);
        obj.__wbg_ptr = ptr;
        LiteralFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        LiteralFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_literal_free(ptr, 0);
    }
    /**
     * @returns {NamedNode}
     */
    get datatype() {
        const ret = wasm.literal_datatype(this.__wbg_ptr);
        return NamedNode.__wrap(ret);
    }
    /**
     * @returns {string}
     */
    get direction() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.literal_direction(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @param {any} other
     * @returns {boolean}
     */
    equals(other) {
        const ret = wasm.literal_equals(this.__wbg_ptr, other);
        return ret !== 0;
    }
    /**
     * @returns {string}
     */
    get language() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.literal_language(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get termType() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.literal_term_type(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    toString() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.literal_toString(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get value() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.literal_value(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) Literal.prototype[Symbol.dispose] = Literal.prototype.free;

export class NamedNode {
    static __wrap(ptr) {
        const obj = Object.create(NamedNode.prototype);
        obj.__wbg_ptr = ptr;
        NamedNodeFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        NamedNodeFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_namednode_free(ptr, 0);
    }
    /**
     * @param {any} other
     * @returns {boolean}
     */
    equals(other) {
        const ret = wasm.namednode_equals(this.__wbg_ptr, other);
        return ret !== 0;
    }
    /**
     * @returns {string}
     */
    get termType() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.namednode_term_type(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    toString() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.namednode_toString(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get value() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.namednode_value(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) NamedNode.prototype[Symbol.dispose] = NamedNode.prototype.free;

class ParserIterator {
    static __wrap(ptr) {
        const obj = Object.create(ParserIterator.prototype);
        obj.__wbg_ptr = ptr;
        ParserIteratorFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        ParserIteratorFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_parseriterator_free(ptr, 0);
    }
    /**
     * @returns {ParserIteratorResult}
     */
    next() {
        const ret = wasm.parseriterator_next(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return ParserIteratorResult.__wrap(ret[0]);
    }
}
if (Symbol.dispose) ParserIterator.prototype[Symbol.dispose] = ParserIterator.prototype.free;

class ParserIteratorResult {
    static __wrap(ptr) {
        const obj = Object.create(ParserIteratorResult.prototype);
        obj.__wbg_ptr = ptr;
        ParserIteratorResultFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        ParserIteratorResultFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_parseriteratorresult_free(ptr, 0);
    }
    /**
     * @returns {boolean}
     */
    get done() {
        const ret = wasm.parseriteratorresult_done(this.__wbg_ptr);
        return ret !== 0;
    }
    /**
     * @returns {Quad | undefined}
     */
    get value() {
        const ret = wasm.parseriteratorresult_value(this.__wbg_ptr);
        return ret === 0 ? undefined : Quad.__wrap(ret);
    }
}
if (Symbol.dispose) ParserIteratorResult.prototype[Symbol.dispose] = ParserIteratorResult.prototype.free;

export class Quad {
    static __wrap(ptr) {
        const obj = Object.create(Quad.prototype);
        obj.__wbg_ptr = ptr;
        QuadFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        QuadFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_quad_free(ptr, 0);
    }
    /**
     * @param {any} other
     * @returns {boolean}
     */
    equals(other) {
        const ret = wasm.quad_equals(this.__wbg_ptr, other);
        return ret !== 0;
    }
    /**
     * @returns {any}
     */
    get graph() {
        const ret = wasm.quad_graph(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {any}
     */
    get object() {
        const ret = wasm.quad_object(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {any}
     */
    get predicate() {
        const ret = wasm.quad_predicate(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {any}
     */
    get subject() {
        const ret = wasm.quad_subject(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {string}
     */
    get termType() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.quad_term_type(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    toString() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.quad_toString(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get value() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.quad_value(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) Quad.prototype[Symbol.dispose] = Quad.prototype.free;

export class Store {
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        StoreFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_store_free(ptr, 0);
    }
    /**
     * @param {any} quad
     */
    add(quad) {
        const ret = wasm.store_add(this.__wbg_ptr, quad);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @param {any} quad
     */
    delete(quad) {
        const ret = wasm.store_delete(this.__wbg_ptr, quad);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @param {any} options
     * @param {any} from_graph_name
     * @returns {string}
     */
    dump(options, from_graph_name) {
        let deferred2_0;
        let deferred2_1;
        try {
            const ret = wasm.store_dump(this.__wbg_ptr, options, from_graph_name);
            var ptr1 = ret[0];
            var len1 = ret[1];
            if (ret[3]) {
                ptr1 = 0; len1 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred2_0 = ptr1;
            deferred2_1 = len1;
            return getStringFromWasm0(ptr1, len1);
        } finally {
            wasm.__wbindgen_free(deferred2_0, deferred2_1, 1);
        }
    }
    /**
     * @param {any} quad
     * @returns {boolean}
     */
    has(quad) {
        const ret = wasm.store_has(this.__wbg_ptr, quad);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return ret[0] !== 0;
    }
    /**
     * @param {any} data
     * @param {any} options
     * @param {any} base_iri
     * @param {any} to_graph_name
     */
    load(data, options, base_iri, to_graph_name) {
        const ret = wasm.store_load(this.__wbg_ptr, data, options, base_iri, to_graph_name);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @param {any} subject
     * @param {any} predicate
     * @param {any} object
     * @param {any} graph_name
     * @returns {Quad[]}
     */
    match(subject, predicate, object, graph_name) {
        const ret = wasm.store_match(this.__wbg_ptr, subject, predicate, object, graph_name);
        if (ret[3]) {
            throw takeFromExternrefTable0(ret[2]);
        }
        var v1 = getArrayJsValueFromWasm0(ret[0], ret[1]);
        wasm.__wbindgen_free(ret[0], ret[1] * 4, 4);
        return v1;
    }
    /**
     * @param {any} quads
     */
    constructor(quads) {
        const ret = wasm.store_new(quads);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        this.__wbg_ptr = ret[0];
        StoreFinalization.register(this, this.__wbg_ptr, this);
        return this;
    }
    /**
     * @param {string} query
     * @param {any} options
     * @returns {any}
     */
    query(query, options) {
        const ptr0 = passStringToWasm0(query, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.store_query(this.__wbg_ptr, ptr0, len0, options);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return takeFromExternrefTable0(ret[0]);
    }
    /**
     * @returns {number}
     */
    get size() {
        const ret = wasm.store_size(this.__wbg_ptr);
        if (ret[2]) {
            throw takeFromExternrefTable0(ret[1]);
        }
        return ret[0] >>> 0;
    }
    /**
     * @param {string} update
     * @param {any} options
     */
    update(update, options) {
        const ptr0 = passStringToWasm0(update, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.store_update(this.__wbg_ptr, ptr0, len0, options);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
}
if (Symbol.dispose) Store.prototype[Symbol.dispose] = Store.prototype.free;

export class Variable {
    static __wrap(ptr) {
        const obj = Object.create(Variable.prototype);
        obj.__wbg_ptr = ptr;
        VariableFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        VariableFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_variable_free(ptr, 0);
    }
    /**
     * @param {any} other
     * @returns {boolean}
     */
    equals(other) {
        const ret = wasm.variable_equals(this.__wbg_ptr, other);
        return ret !== 0;
    }
    /**
     * @returns {string}
     */
    get termType() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.variable_term_type(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    toString() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.variable_toString(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @returns {string}
     */
    get value() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.variable_value(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) Variable.prototype[Symbol.dispose] = Variable.prototype.free;

/**
 * @param {string | null} [value]
 * @returns {BlankNode}
 */
export function blankNode(value) {
    var ptr0 = isLikeNone(value) ? 0 : passStringToWasm0(value, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
    var len0 = WASM_VECTOR_LEN;
    const ret = wasm.blankNode(ptr0, len0);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return BlankNode.__wrap(ret[0]);
}

/**
 * @returns {DefaultGraph}
 */
export function defaultGraph() {
    const ret = wasm.defaultGraph();
    return DefaultGraph.__wrap(ret);
}

/**
 * @param {any} original
 * @returns {any}
 */
export function fromQuad(original) {
    const ret = wasm.fromQuad(original);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return takeFromExternrefTable0(ret[0]);
}

/**
 * @param {any} original
 * @returns {any}
 */
export function fromTerm(original) {
    const ret = wasm.fromTerm(original);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return takeFromExternrefTable0(ret[0]);
}

/**
 * @param {string | null | undefined} value
 * @param {any} language_or_datatype
 * @returns {Literal}
 */
export function literal(value, language_or_datatype) {
    var ptr0 = isLikeNone(value) ? 0 : passStringToWasm0(value, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
    var len0 = WASM_VECTOR_LEN;
    const ret = wasm.literal(ptr0, len0, language_or_datatype);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return Literal.__wrap(ret[0]);
}

export function main() {
    wasm.main();
}

/**
 * @param {string} value
 * @returns {NamedNode}
 */
export function namedNode(value) {
    const ptr0 = passStringToWasm0(value, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
    const len0 = WASM_VECTOR_LEN;
    const ret = wasm.namedNode(ptr0, len0);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return NamedNode.__wrap(ret[0]);
}

/**
 * @param {any} input
 * @param {any} options
 * @returns {any}
 */
export function parse(input, options) {
    const ret = wasm.parse(input, options);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return takeFromExternrefTable0(ret[0]);
}

/**
 * @param {any} subject
 * @param {any} predicate
 * @param {any} object
 * @param {any} graph
 * @returns {Quad}
 */
export function quad(subject, predicate, object, graph) {
    const ret = wasm.quad(subject, predicate, object, graph);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return Quad.__wrap(ret[0]);
}

/**
 * @param {any} subject
 * @param {any} predicate
 * @param {any} object
 * @returns {Quad}
 */
export function triple(subject, predicate, object) {
    const ret = wasm.triple(subject, predicate, object);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return Quad.__wrap(ret[0]);
}

/**
 * @param {string} value
 * @returns {Variable}
 */
export function variable(value) {
    const ptr0 = passStringToWasm0(value, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
    const len0 = WASM_VECTOR_LEN;
    const ret = wasm.variable(ptr0, len0);
    if (ret[2]) {
        throw takeFromExternrefTable0(ret[1]);
    }
    return Variable.__wrap(ret[0]);
}
function __wbg_get_imports() {
    const import0 = {
        __proto__: null,
        __wbg_Error_30c8987f7c2ed4e2: function(arg0, arg1) {
            const ret = Error(getStringFromWasm0(arg0, arg1));
            return ret;
        },
        __wbg___wbindgen_debug_string_4687d8d8c2017d52: function(arg0, arg1) {
            const ret = debugString(arg1);
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32(arg0 + 4 * 1, len1, true);
            getDataViewMemory0().setInt32(arg0 + 4 * 0, ptr1, true);
        },
        __wbg___wbindgen_is_falsy_16bd49b68658263e: function(arg0) {
            const ret = !arg0;
            return ret;
        },
        __wbg___wbindgen_is_function_1f9d30630b8b1d3d: function(arg0) {
            const ret = typeof(arg0) === 'function';
            return ret;
        },
        __wbg___wbindgen_is_null_e343b7d08827ba72: function(arg0) {
            const ret = arg0 === null;
            return ret;
        },
        __wbg___wbindgen_is_object_3c45d4f2dde4e749: function(arg0) {
            const val = arg0;
            const ret = typeof(val) === 'object' && val !== null;
            return ret;
        },
        __wbg___wbindgen_is_string_90b56bc79aad6f6c: function(arg0) {
            const ret = typeof(arg0) === 'string';
            return ret;
        },
        __wbg___wbindgen_is_undefined_8865fb403f8fe9d8: function(arg0) {
            const ret = arg0 === undefined;
            return ret;
        },
        __wbg___wbindgen_string_get_0380ccaa2f57f0d9: function(arg0, arg1) {
            const obj = arg1;
            const ret = typeof(obj) === 'string' ? obj : undefined;
            var ptr1 = isLikeNone(ret) ? 0 : passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            var len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32(arg0 + 4 * 1, len1, true);
            getDataViewMemory0().setInt32(arg0 + 4 * 0, ptr1, true);
        },
        __wbg___wbindgen_throw_41e9ee4f547fc59a: function(arg0, arg1) {
            throw new Error(getStringFromWasm0(arg0, arg1));
        },
        __wbg__wbg_cb_unref_dcc1a90847f04c41: function(arg0) {
            arg0._wbg_cb_unref();
        },
        __wbg_asyncIterator_a6ee5b0e4aee2db8: function() {
            const ret = Symbol.asyncIterator;
            return ret;
        },
        __wbg_asyncparseriterator_new: function(arg0) {
            const ret = AsyncParserIterator.__wrap(arg0);
            return ret;
        },
        __wbg_blanknode_new: function(arg0) {
            const ret = BlankNode.__wrap(arg0);
            return ret;
        },
        __wbg_call_187d372bd5fdd4aa: function() { return handleError(function (arg0, arg1, arg2) {
            const ret = arg0.call(arg1, arg2);
            return ret;
        }, arguments); },
        __wbg_call_6137034ef55c9d0f: function() { return handleError(function (arg0, arg1) {
            const ret = arg0.call(arg1);
            return ret;
        }, arguments); },
        __wbg_defaultgraph_new: function(arg0) {
            const ret = DefaultGraph.__wrap(arg0);
            return ret;
        },
        __wbg_done_b41a1d26cdb37fb6: function(arg0) {
            const ret = arg0.done;
            return ret;
        },
        __wbg_error_757e9472f8410341: function(arg0, arg1) {
            let deferred0_0;
            let deferred0_1;
            try {
                deferred0_0 = arg0;
                deferred0_1 = arg1;
                console.error(getStringFromWasm0(arg0, arg1));
            } finally {
                wasm.__wbindgen_free(deferred0_0, deferred0_1, 1);
            }
        },
        __wbg_getRandomValues_a608c4436c19407a: function() { return handleError(function (arg0, arg1) {
            globalThis.crypto.getRandomValues(getArrayU8FromWasm0(arg0, arg1));
        }, arguments); },
        __wbg_get_31af05bd4842a84f: function() { return handleError(function (arg0, arg1) {
            const ret = Reflect.get(arg0, arg1);
            return ret;
        }, arguments); },
        __wbg_get_658f6698067d9515: function() { return handleError(function (arg0, arg1) {
            const ret = Reflect.get(arg0, arg1);
            return ret;
        }, arguments); },
        __wbg_has_5d6706e5209576c1: function() { return handleError(function (arg0, arg1) {
            const ret = Reflect.has(arg0, arg1);
            return ret;
        }, arguments); },
        __wbg_instanceof_Uint8Array_828cef2aaacafc31: function(arg0) {
            let result;
            try {
                result = arg0 instanceof Uint8Array;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_iterator_e3c31c892080e444: function() {
            const ret = Symbol.iterator;
            return ret;
        },
        __wbg_length_7f3c00c40364105e: function(arg0) {
            const ret = arg0.length;
            return ret;
        },
        __wbg_literal_new: function(arg0) {
            const ret = Literal.__wrap(arg0);
            return ret;
        },
        __wbg_namednode_new: function(arg0) {
            const ret = NamedNode.__wrap(arg0);
            return ret;
        },
        __wbg_new_227d7c05414eb861: function() {
            const ret = new Error();
            return ret;
        },
        __wbg_new_28744009d011f847: function() {
            const ret = new Map();
            return ret;
        },
        __wbg_new_343a093a3c2ffb4e: function(arg0, arg1) {
            const ret = new Error(getStringFromWasm0(arg0, arg1));
            return ret;
        },
        __wbg_new_57035ae00cb280dc: function(arg0, arg1) {
            const ret = new URIError(getStringFromWasm0(arg0, arg1));
            return ret;
        },
        __wbg_new_ee2291f50781bf1d: function() {
            const ret = new Array();
            return ret;
        },
        __wbg_new_typed_b01cb72a8af741a3: function(arg0, arg1) {
            try {
                var state0 = {a: arg0, b: arg1};
                var cb0 = (arg0, arg1) => {
                    const a = state0.a;
                    state0.a = 0;
                    try {
                        return wasm_bindgen_a96e599690d83656___convert__closures_____invoke___js_sys_b6c5f4cd0c172f4___Function_fn_wasm_bindgen_a96e599690d83656___JsValue_____wasm_bindgen_a96e599690d83656___sys__Undefined___js_sys_b6c5f4cd0c172f4___Function_fn_wasm_bindgen_a96e599690d83656___JsValue_____wasm_bindgen_a96e599690d83656___sys__Undefined_______true_(a, state0.b, arg0, arg1);
                    } finally {
                        state0.a = a;
                    }
                };
                const ret = new Promise(cb0);
                return ret;
            } finally {
                state0.a = 0;
            }
        },
        __wbg_next_33784799010f1bbe: function(arg0) {
            const ret = arg0.next;
            return ret;
        },
        __wbg_next_762aca09b0915bfc: function() { return handleError(function (arg0) {
            const ret = arg0.next();
            return ret;
        }, arguments); },
        __wbg_next_f4aac29c42af995c: function() { return handleError(function (arg0) {
            const ret = arg0.next();
            return ret;
        }, arguments); },
        __wbg_now_aa4ccb83129e9e55: function() {
            const ret = Date.now();
            return ret;
        },
        __wbg_parseriterator_new: function(arg0) {
            const ret = ParserIterator.__wrap(arg0);
            return ret;
        },
        __wbg_parseriteratorresult_new: function(arg0) {
            const ret = ParserIteratorResult.__wrap(arg0);
            return ret;
        },
        __wbg_prototypesetcall_bc27214492979395: function(arg0, arg1, arg2) {
            Uint8Array.prototype.set.call(getArrayU8FromWasm0(arg0, arg1), arg2);
        },
        __wbg_push_2baf45db356cf468: function(arg0, arg1) {
            const ret = arg0.push(arg1);
            return ret;
        },
        __wbg_quad_new: function(arg0) {
            const ret = Quad.__wrap(arg0);
            return ret;
        },
        __wbg_queueMicrotask_9833f9a49df95a49: function(arg0) {
            const ret = arg0.queueMicrotask;
            return ret;
        },
        __wbg_queueMicrotask_a72f977e97f23c5f: function(arg0) {
            queueMicrotask(arg0);
        },
        __wbg_resolve_0076e10020304ede: function(arg0) {
            const ret = Promise.resolve(arg0);
            return ret;
        },
        __wbg_set_145a351398b48c65: function() { return handleError(function (arg0, arg1, arg2) {
            const ret = Reflect.set(arg0, arg1, arg2);
            return ret;
        }, arguments); },
        __wbg_set_6ae97e73113c4f0b: function(arg0, arg1, arg2) {
            const ret = arg0.set(arg1, arg2);
            return ret;
        },
        __wbg_stack_3b0d974bbf31e44f: function(arg0, arg1) {
            const ret = arg1.stack;
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32(arg0 + 4 * 1, len1, true);
            getDataViewMemory0().setInt32(arg0 + 4 * 0, ptr1, true);
        },
        __wbg_static_accessor_GLOBAL_266715b9d96ba635: function() {
            const ret = typeof global === 'undefined' ? null : global;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_GLOBAL_THIS_10fb7dc1ae063179: function() {
            const ret = typeof globalThis === 'undefined' ? null : globalThis;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_SELF_0b583911f537483a: function() {
            const ret = typeof self === 'undefined' ? null : self;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_WINDOW_d7f903d1508cbdc4: function() {
            const ret = typeof window === 'undefined' ? null : window;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_then_c949d5a25a4e78f8: function(arg0, arg1, arg2) {
            const ret = arg0.then(arg1, arg2);
            return ret;
        },
        __wbg_then_e71170d78fcf8954: function(arg0, arg1) {
            const ret = arg0.then(arg1);
            return ret;
        },
        __wbg_value_f3c585ee8f5ba40c: function(arg0) {
            const ret = arg0.value;
            return ret;
        },
        __wbg_variable_new: function(arg0) {
            const ret = Variable.__wrap(arg0);
            return ret;
        },
        __wbg_warn_441293781f784dab: function(arg0, arg1) {
            console.warn(getStringFromWasm0(arg0, arg1));
        },
        __wbindgen_generic_0000000000000001: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [Externref], shim_idx: 108, ret: Result(Unit), inner_ret: Some(Result(Unit)) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_a96e599690d83656___convert__closures_____invoke___wasm_bindgen_a96e599690d83656___JsValue__core_37ee0ce0c4cd57d5___result__Result_____wasm_bindgen_a96e599690d83656___JsError___true_);
            return ret;
        },
        __wbindgen_generic_0000000000000002: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [], shim_idx: 53, ret: Externref, inner_ret: Some(Externref) }, mutable: false }) -> Externref`.
            const ret = makeClosure(arg0, arg1, wasm_bindgen_a96e599690d83656___convert__closures_____invoke___wasm_bindgen_a96e599690d83656___JsValue__true_);
            return ret;
        },
        __wbindgen_generic_0000000000000003: function(arg0, arg1) {
            // Cast intrinsic for `Ref(String) -> Externref`.
            const ret = getStringFromWasm0(arg0, arg1);
            return ret;
        },
        __wbindgen_generic_0000000000000004: function(arg0, arg1) {
            var v0 = getArrayJsValueFromWasm0(arg0, arg1);
            wasm.__wbindgen_free(arg0, arg1 * 4, 4);
            // Cast intrinsic for `Vector(RustStruct { name: "Quad", unique_crate_identifier: "oxigraph-js-35065bb5adc4414f" }) -> Externref`.
            const ret = v0;
            return ret;
        },
        __wbindgen_init_externref_table: function() {
            const table = wasm.__wbindgen_externrefs;
            const offset = table.grow(4);
            table.set(0, undefined);
            table.set(offset + 0, undefined);
            table.set(offset + 1, null);
            table.set(offset + 2, true);
            table.set(offset + 3, false);
        },
    };
    return {
        __proto__: null,
        "./web_bg.js": import0,
    };
}

function wasm_bindgen_a96e599690d83656___convert__closures_____invoke___wasm_bindgen_a96e599690d83656___JsValue__true_(arg0, arg1) {
    const ret = wasm.wasm_bindgen_a96e599690d83656___convert__closures_____invoke___wasm_bindgen_a96e599690d83656___JsValue__true_(arg0, arg1);
    return ret;
}

function wasm_bindgen_a96e599690d83656___convert__closures_____invoke___wasm_bindgen_a96e599690d83656___JsValue__core_37ee0ce0c4cd57d5___result__Result_____wasm_bindgen_a96e599690d83656___JsError___true_(arg0, arg1, arg2) {
    const ret = wasm.wasm_bindgen_a96e599690d83656___convert__closures_____invoke___wasm_bindgen_a96e599690d83656___JsValue__core_37ee0ce0c4cd57d5___result__Result_____wasm_bindgen_a96e599690d83656___JsError___true_(arg0, arg1, arg2);
    if (ret[1]) {
        throw takeFromExternrefTable0(ret[0]);
    }
}

function wasm_bindgen_a96e599690d83656___convert__closures_____invoke___js_sys_b6c5f4cd0c172f4___Function_fn_wasm_bindgen_a96e599690d83656___JsValue_____wasm_bindgen_a96e599690d83656___sys__Undefined___js_sys_b6c5f4cd0c172f4___Function_fn_wasm_bindgen_a96e599690d83656___JsValue_____wasm_bindgen_a96e599690d83656___sys__Undefined_______true_(arg0, arg1, arg2, arg3) {
    wasm.wasm_bindgen_a96e599690d83656___convert__closures_____invoke___js_sys_b6c5f4cd0c172f4___Function_fn_wasm_bindgen_a96e599690d83656___JsValue_____wasm_bindgen_a96e599690d83656___sys__Undefined___js_sys_b6c5f4cd0c172f4___Function_fn_wasm_bindgen_a96e599690d83656___JsValue_____wasm_bindgen_a96e599690d83656___sys__Undefined_______true_(arg0, arg1, arg2, arg3);
}

const AsyncParserIteratorFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_asyncparseriterator_free(ptr, 1));
const BlankNodeFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_blanknode_free(ptr, 1));
const DefaultGraphFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_defaultgraph_free(ptr, 1));
const LiteralFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_literal_free(ptr, 1));
const NamedNodeFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_namednode_free(ptr, 1));
const ParserIteratorFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_parseriterator_free(ptr, 1));
const ParserIteratorResultFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_parseriteratorresult_free(ptr, 1));
const QuadFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_quad_free(ptr, 1));
const StoreFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_store_free(ptr, 1));
const VariableFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_variable_free(ptr, 1));

function addToExternrefTable0(obj) {
    const idx = wasm.__externref_table_alloc();
    wasm.__wbindgen_externrefs.set(idx, obj);
    return idx;
}

const CLOSURE_DTORS = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(state => wasm.__wbindgen_destroy_closure(state.a, state.b));

function debugString(val) {
    // primitive types
    const type = typeof val;
    if (type == 'number' || type == 'boolean' || val == null) {
        return  `${val}`;
    }
    if (type == 'string') {
        return `"${val}"`;
    }
    if (type == 'symbol') {
        const description = val.description;
        if (description == null) {
            return 'Symbol';
        } else {
            return `Symbol(${description})`;
        }
    }
    if (type == 'function') {
        const name = val.name;
        if (typeof name == 'string' && name.length > 0) {
            return `Function(${name})`;
        } else {
            return 'Function';
        }
    }
    // objects
    if (Array.isArray(val)) {
        const length = val.length;
        let debug = '[';
        if (length > 0) {
            debug += debugString(val[0]);
        }
        for(let i = 1; i < length; i++) {
            debug += ', ' + debugString(val[i]);
        }
        debug += ']';
        return debug;
    }
    // Test for built-in
    const builtInMatches = /\[object ([^\]]+)\]/.exec(toString.call(val));
    let className;
    if (builtInMatches && builtInMatches.length > 1) {
        className = builtInMatches[1];
    } else {
        // Failed to match the standard '[object ClassName]'
        return toString.call(val);
    }
    if (className == 'Object') {
        // we're a user defined class or Object
        // JSON.stringify avoids problems with cycles, and is generally much
        // easier than looping through ownProperties of `val`.
        try {
            return 'Object(' + JSON.stringify(val) + ')';
        } catch (_) {
            return 'Object';
        }
    }
    // errors
    if (val instanceof Error) {
        return `${val.name}: ${val.message}\n${val.stack}`;
    }
    // TODO we could test for more things here, like `Set`s and `Map`s.
    return className;
}

function getArrayJsValueFromWasm0(ptr, len) {
    ptr = ptr >>> 0;
    const mem = getDataViewMemory0();
    const result = [];
    for (let i = ptr; i < ptr + 4 * len; i += 4) {
        result.push(wasm.__wbindgen_externrefs.get(mem.getUint32(i, true)));
    }
    wasm.__externref_drop_slice(ptr, len);
    return result;
}

function getArrayU8FromWasm0(ptr, len) {
    ptr = ptr >>> 0;
    return getUint8ArrayMemory0().subarray(ptr / 1, ptr / 1 + len);
}

let cachedDataViewMemory0 = null;
function getDataViewMemory0() {
    if (cachedDataViewMemory0 === null || cachedDataViewMemory0.buffer.detached === true || (cachedDataViewMemory0.buffer.detached === undefined && cachedDataViewMemory0.buffer !== wasm.memory.buffer)) {
        cachedDataViewMemory0 = new DataView(wasm.memory.buffer);
    }
    return cachedDataViewMemory0;
}

function getStringFromWasm0(ptr, len) {
    return decodeText(ptr >>> 0, len);
}

let cachedUint8ArrayMemory0 = null;
function getUint8ArrayMemory0() {
    if (cachedUint8ArrayMemory0 === null || cachedUint8ArrayMemory0.byteLength === 0) {
        cachedUint8ArrayMemory0 = new Uint8Array(wasm.memory.buffer);
    }
    return cachedUint8ArrayMemory0;
}

function handleError(f, args) {
    try {
        return f.apply(this, args);
    } catch (e) {
        const idx = addToExternrefTable0(e);
        wasm.__wbindgen_exn_store(idx);
    }
}

function isLikeNone(x) {
    return x === undefined || x === null;
}

function makeClosure(arg0, arg1, f) {
    const state = { a: arg0, b: arg1, cnt: 1 };
    const real = (...args) => {

        // First up with a closure we increment the internal reference
        // count. This ensures that the Rust closure environment won't
        // be deallocated while we're invoking it.
        state.cnt++;
        try {
            return f(state.a, state.b, ...args);
        } finally {
            real._wbg_cb_unref();
        }
    };
    real._wbg_cb_unref = () => {
        if (--state.cnt === 0) {
            wasm.__wbindgen_destroy_closure(state.a, state.b);
            state.a = 0;
            CLOSURE_DTORS.unregister(state);
        }
    };
    CLOSURE_DTORS.register(real, state, state);
    return real;
}

function makeMutClosure(arg0, arg1, f) {
    const state = { a: arg0, b: arg1, cnt: 1 };
    const real = (...args) => {

        // First up with a closure we increment the internal reference
        // count. This ensures that the Rust closure environment won't
        // be deallocated while we're invoking it.
        state.cnt++;
        const a = state.a;
        state.a = 0;
        try {
            return f(a, state.b, ...args);
        } finally {
            state.a = a;
            real._wbg_cb_unref();
        }
    };
    real._wbg_cb_unref = () => {
        if (--state.cnt === 0) {
            wasm.__wbindgen_destroy_closure(state.a, state.b);
            state.a = 0;
            CLOSURE_DTORS.unregister(state);
        }
    };
    CLOSURE_DTORS.register(real, state, state);
    return real;
}

function passStringToWasm0(arg, malloc, realloc) {
    if (realloc === undefined) {
        const buf = cachedTextEncoder.encode(arg);
        const ptr = malloc(buf.length, 1) >>> 0;
        getUint8ArrayMemory0().subarray(ptr, ptr + buf.length).set(buf);
        WASM_VECTOR_LEN = buf.length;
        return ptr;
    }

    let len = arg.length;
    let ptr = malloc(len, 1) >>> 0;

    const mem = getUint8ArrayMemory0();

    let offset = 0;

    for (; offset < len; offset++) {
        const code = arg.charCodeAt(offset);
        if (code > 0x7F) break;
        mem[ptr + offset] = code;
    }
    if (offset !== len) {
        if (offset !== 0) {
            arg = arg.slice(offset);
        }
        ptr = realloc(ptr, len, len = offset + arg.length * 3, 1) >>> 0;
        const view = getUint8ArrayMemory0().subarray(ptr + offset, ptr + len);
        const ret = cachedTextEncoder.encodeInto(arg, view);

        offset += ret.written;
        ptr = realloc(ptr, len, offset, 1) >>> 0;
    }

    WASM_VECTOR_LEN = offset;
    return ptr;
}

function takeFromExternrefTable0(idx) {
    const value = wasm.__wbindgen_externrefs.get(idx);
    wasm.__externref_table_dealloc(idx);
    return value;
}

let cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
cachedTextDecoder.decode();
const MAX_SAFARI_DECODE_BYTES = 2146435072;
let numBytesDecoded = 0;
function decodeText(ptr, len) {
    numBytesDecoded += len;
    if (numBytesDecoded >= MAX_SAFARI_DECODE_BYTES) {
        cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });
        cachedTextDecoder.decode();
        numBytesDecoded = len;
    }
    return cachedTextDecoder.decode(getUint8ArrayMemory0().subarray(ptr, ptr + len));
}

const cachedTextEncoder = new TextEncoder();

if (!('encodeInto' in cachedTextEncoder)) {
    cachedTextEncoder.encodeInto = function (arg, view) {
        const buf = cachedTextEncoder.encode(arg);
        view.set(buf);
        return {
            read: arg.length,
            written: buf.length
        };
    };
}

let WASM_VECTOR_LEN = 0;

let wasmModule, wasmInstance, wasm;
function __wbg_finalize_init(instance, module) {
    wasmInstance = instance;
    wasm = instance.exports;
    wasmModule = module;
    cachedDataViewMemory0 = null;
    cachedUint8ArrayMemory0 = null;
    wasm.__wbindgen_start();
    return wasm;
}

async function __wbg_load(module, imports) {
    if (typeof Response === 'function' && module instanceof Response) {
        if (!module.ok) {
            throw new Error(`failed to fetch Wasm: ${module.status} ${module.statusText} fetching '${module.url}'`);
        }

        if (typeof WebAssembly.instantiateStreaming === 'function') {
            try {
                return await WebAssembly.instantiateStreaming(module, imports);
            } catch (e) {
                const validResponse = expectedResponseType(module.type);

                if (validResponse && module.headers.get('Content-Type') !== 'application/wasm') {
                    console.warn("`WebAssembly.instantiateStreaming` failed because your server does not serve Wasm with `application/wasm` MIME type. Falling back to `WebAssembly.instantiate` which is slower. Original error:\n", e);

                } else { throw e; }
            }
        }

        const bytes = await module.arrayBuffer();
        return await WebAssembly.instantiate(bytes, imports);
    } else {
        const instance = await WebAssembly.instantiate(module, imports);

        if (instance instanceof WebAssembly.Instance) {
            return { instance, module };
        } else {
            return instance;
        }
    }

    function expectedResponseType(type) {
        switch (type) {
            case 'basic': case 'cors': case 'default': return true;
        }
        return false;
    }
}

function initSync(module) {
    if (wasm !== undefined) return wasm;


    if (module !== undefined) {
        if (Object.getPrototypeOf(module) === Object.prototype) {
            ({module} = module)
        } else {
            console.warn('using deprecated parameters for `initSync()`; pass a single object instead')
        }
    }

    const imports = __wbg_get_imports();
    if (!(module instanceof WebAssembly.Module)) {
        module = new WebAssembly.Module(module);
    }
    const instance = new WebAssembly.Instance(module, imports);
    return __wbg_finalize_init(instance, module);
}

async function __wbg_init(module_or_path) {
    if (wasm !== undefined) return wasm;


    if (module_or_path !== undefined) {
        if (Object.getPrototypeOf(module_or_path) === Object.prototype) {
            ({module_or_path} = module_or_path)
        } else {
            console.warn('using deprecated parameters for the initialization function; pass a single object instead')
        }
    }

    if (module_or_path === undefined) {
        module_or_path = new URL('web_bg.wasm', import.meta.url);
    }
    const imports = __wbg_get_imports();

    if (typeof module_or_path === 'string' || (typeof Request === 'function' && module_or_path instanceof Request) || (typeof URL === 'function' && module_or_path instanceof URL)) {
        module_or_path = fetch(module_or_path);
    }

    const { instance, module } = await __wbg_load(await module_or_path, imports);

    return __wbg_finalize_init(instance, module);
}

export { initSync, __wbg_init as default };
