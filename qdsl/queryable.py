from collections import Counter
from io import StringIO
from itertools import chain

from qdsl.tree import Branch, Leaf, flatten
from qdsl.boolean import Boolean, Predicate


# Optimization: Special case queries where possible.
def desugar(raw):
    """
    Queries have two parts, both optional: a name query and one or more value
    queries. If there are two parts, they're in a tuple. The first element is
    for the name, and all remaining elements are for the value. The value queries
    are all "or'd", and the result is "anded" with the name query.

    We convert each query into a python function and optimize some special cases.
    """
    def desugar_name(query):
        # None means match everything. If you want to match literal None, use eq(None).
        if query is None:
            def predicate(node):
                return True
        elif isinstance(query, Boolean):
            f = query.to_pyfunc()

            def predicate(node):
                return f(node._name)
        elif callable(query):
            def predicate(node):
                return query(node._name)
        else:
            def predicate(node):
                return node._name == query
        return predicate

    def desugar_value(query):
        # None means match everything. If you want to match literal None, use eq(None).
        if query is None:
            def predicate(node):
                return True
        elif isinstance(query, Boolean):
            f = query.to_pyfunc()

            def predicate(node):
                return any(f(v) for v in node._value)
        elif callable(query):
            def predicate(node):
                return any(query(v) for v in node._value)
        else:
            def predicate(node):
                return any(query == v for v in node._value)
        return predicate

    if not isinstance(raw, tuple):
        predicate = desugar_name(raw)
    else:
        namep = raw[0]
        valp = [desugar_value(q) for q in raw[1:]]
        if namep is not None:
            namep = desugar_name(namep)

            def predicate(node):
                return namep(node) and any(p(node) for p in valp)
        else:
            def predicate(node):
                return any(p(node) for p in valp)

    return predicate


class Queryable(object):
    __slots__ = ["_children"]

    def __init__(self, children=None):
        self._children = tuple(children or [])

    def _run_query(self, query, nodes):
        results = []
        for parent in nodes:
            try:
                results.extend(gc for gc in parent._children if query(gc))
            except:
                pass
        return results

    def query(self, query, desugared=False):
        if not desugared:
            query = desugar(query)

        results = self._run_query(query, self._children)
        return Queryable(results)

    def __getattr__(self, key):
        return self.__getitem__(key)

    def __getitem__(self, query):
        if isinstance(query, (int, slice)):
            if isinstance(query, int):
                return Queryable([self._children[query]])

            if isinstance(query, slice):
                return Queryable(self._children[query])

        return self.query(query)

    def keys(self):
        results = []
        seen = set()
        for parent in self._children:
            for c in parent._children:
                name = c._name
                if name not in seen:
                    seen.add(name)
                    results.append(name)
        return sorted(results)

    def find(self, *queries):
        res = []
        queries = [desugar(q) for q in queries]
        # Optimization: querying the entire flattened tree at once is equivalent to querying individual nodes.
        for c in self._children:
            cur = list(flatten(c))
            for q in queries:
                if cur:
                    cur = self._run_query(q, cur)
            if cur:
                res.extend(cur)
        return Queryable(res)

    # Optimization: simplify the where API so we don't need a separate WhereBoolean hierarchy.
    def where(self, query):
        res = []
        if callable(query):
            # it's a lambda
            for c in self._children:
                try:
                    # given lambdas the Queryable API for each node.
                    if query(Queryable([c])):
                        res.append(c)
                except:
                    pass
        else:
            # it's a Boolean created with q
            query = query.to_pyfunc()
            for c in self._children:
                try:
                    if query(c._children):
                        res.append(c)
                except:
                    pass
        return Queryable(res)

    def upto(self, query):
        query = desugar(query)
        res = []
        seen = set()
        for c in self._children:
            p = c._parent
            while p is not None and not query(p):
                p = p._parent

            if p is not None and p not in seen:
                seen.add(p)
                res.append(p)

        return Queryable(res)

    def get_crumbs(self):
        res = []
        seen = set()
        for c in self._children:
            segments = []
            cur = c
            while cur is not None:
                name = cur._name
                if name is not None:
                    segments.append(name)
                cur = cur._parent
            path = ".".join(reversed(segments))
            if path not in seen:
                seen.add(path)
                res.append(path)
        return sorted(res)

    @property
    def parents(self):
        res = []
        seen = set()
        for c in self._children:
            p = c._parent
            if p is not None and p not in seen:
                seen.add(p)
                res.append(p)
        return Queryable(res)

    @property
    def roots(self):
        res = []
        seen = set()
        for c in self._children:
            p = c._parent
            while p is not None:
                gp = p._parent
                if gp is None and p not in seen:
                    seen.add(p)
                    res.append(p)
                p = p._parent
        return Queryable(res)

    def _values(self):
        return chain.from_iterable(c._value for c in self._children)

    @property
    def value(self):
        return next(self._values())

    @property
    def values(self):
        return sorted(self._values())

    @property
    def unique_values(self):
        return sorted(set(self._values()))

    def most_common(self, n=None):
        return Counter(self._values()).most_common(n)

    def to_df(self):
        """ Convert children to pandas Dataframe. """
        import pandas as pd
        res = []

        for parent in self._children:
            try:
                res.append({c._name: c._value[0] for c in parent._children if len(c._value) == 1})
            except:
                pass

        return pd.DataFrame(res)

    def __iter__(self):
        for c in self._children:
            yield Queryable([c])

    def __iadd__(self, other):
        self._children = self._children + other._children
        return self

    def __add__(self, other):
        return Queryable(self._children + other._children)

    def __bool__(self):
        return bool(self._children)

    def __len__(self):
        return len(self._children)

    def __dir__(self):
        return self.keys()

    def __repr__(self):
        out = StringIO()
        for c in self._children:
            out.write(repr(c))
        contents = out.getvalue()
        out.close()
        return contents


def q(name, value=None):
    predicate = desugar(name) if value is None else desugar((name, value))

    # Optimization: where predicates are just regular predicates applied
    # to all children to see if the parent should be kept. The "where" function
    # will handle passing the children instead of the usual node by node querying
    # of grandchildren.
    def inner(nodes):
        return any(predicate(n) for n in nodes)

    return Predicate(inner)


# Optimization: use tuples instead of lists for values and children.
def to_queryable(raw):
    """
    Generic data is made of dictionaries, lists, and primitives. Assume lists
    contain only dictionaries or primitives. If the value side of a dict key is a
    list and the list is full of primitives, a Leaf is generated with the list as
    its value. If the list contains dicts, a Branch is generated for each one,
    and each Branch is named by the original key. Nested lists are recursively
    flattened.
    """
    def convert(data):
        results = []
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    results.append(Branch(k, children=tuple(convert(v))))
                elif isinstance(v, list):
                    if v:
                        # Assume all list values have the same type (list, dict, or primitive).
                        if isinstance(v[0], (list, dict)):
                            for i in v:
                                results.append(Branch(k, children=tuple(convert(i))))
                        else:
                            results.append(Leaf(k, tuple(v)))
                else:
                    results.append(Leaf(k, (v,)))
        elif isinstance(data, list):
            # recursive flattening
            for v in data:
                results.extend(convert(v))
        else:
            raise Exception("Unrecognized data type: {t}".format(t=type(data)))

        return results

    return Queryable([Branch(children=tuple(convert(raw)))])
