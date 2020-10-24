from collections import Counter
from io import StringIO
from itertools import chain

from qdsl.tree import Branch, Leaf, flatten
from qdsl.boolean import Boolean, pred

ANY = None


# Optimization: Special case queries where possible.
def desugar(raw):
    """
    Queries have two parts, both optional: a name query and one or more value
    queries. If there are two parts, they're in a tuple. The first element is
    for the name, and all remaining elements are for the value. The value queries
    are all "or'd", and the result is "anded" with the name query.

    We convert the raw query into a python function, optimizing special cases.
    """
    def desugar_name(query):
        if query is None:
            # None means match everything. If you want to match literal None, use eq(None).
            def predicate(node):
                return True
        elif isinstance(query, Boolean):
            # It's some Boolean expression. Compile it to a regular function.
            f = query.to_pyfunc()

            def predicate(node):
                return f(node._name)
        elif callable(query):
            # It's a lambda or regular predicate function
            def predicate(node):
                return query(node._name)
        else:
            # It's some primitive like a string or number.
            def predicate(node):
                return node._name == query
        return predicate

    def desugar_value(query):
        if query is None:
            # None means match everything. If you want to match literal None, use eq(None).
            def predicate(node):
                return True
        elif isinstance(query, Boolean):
            # It's some Boolean expression. Compile it to a regular function.
            f = query.to_pyfunc()

            def predicate(node):
                return any(f(v) for v in node._value)
        elif callable(query):
            # It's a lambda or regular predicate function
            def predicate(node):
                return any(query(v) for v in node._value)
        else:
            # It's some primitive like a string or number.
            def predicate(node):
                return any(query == v for v in node._value)
        return predicate

    if not isinstance(raw, tuple):
        # If the query isn't a tuple, we're just working on the name.
        predicate = desugar_name(raw)
    else:
        # It's a tuple, so there's a name query and at least one value query.
        namep = raw[0]
        valp = [desugar_value(q) for q in raw[1:]]
        if namep is None:
            # if the name query is None, that means all names are accepted. We
            # don't even have to test them.
            def predicate(node):
                return any(p(node) for p in valp)
        else:
            namep = desugar_name(namep)

            def predicate(node):
                return namep(node) and any(p(node) for p in valp)

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
            try:
                for c in parent._children:
                    name = c._name
                    if name not in seen:
                        seen.add(name)
                        results.append(name)
            except:
                pass
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
                    # give lambdas the Queryable API for each node.
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

    def order_by(self, selector, reverse=False):
        def predicate(node):
            res = selector(node)
            if isinstance(res, (list, tuple)):
                return [r.values for r in res]
            return res.values

        return Queryable(sorted(self, key=predicate, reverse=reverse))

    def select(self, selector):
        """
        Pass a lambda or function. It'll be given a Queryable of each node
        and should return a tuple of query results.

        Examples:

            # perform some query.
            bad = conf.status[endswith("Statuses")].where(q("restartCount", gt(2)) & q("ready", False))

            # select the name, podIP from the status, restartCount, and terminated message.
            results = bad.select(lambda b: (b.name, b.upto("status").podIP, b.restartCount, b.lastState.terminated.message))

            # you also can nest selects, and their results will be flattened.
            # this selects name and restartCount as well as the exitCode and message from lastState.terminated.
            results = bad.select(lambda s: (s.name, s.restartCount, s.lastState.terminated.select(lambda t: (t.exitCode, t.message))))
        """
        results = []
        for c in self._children:
            res = selector(Queryable([c]))
            res = res if isinstance(res, (list, tuple)) else (res,)
            tmp = []
            for r in res:
                if isinstance(r, dict):
                    for k, v in r.items():
                        for i in v._children:
                            if i._name is None:
                                tmp.extend(i._children)
                            else:
                                if isinstance(i, Branch):
                                    tmp.append(Branch(k, i._value, i._children, set_parents=False))
                                else:
                                    tmp.append(Leaf(k, i._value))
                else:
                    for i in r._children:
                        if i._name is None:
                            tmp.extend(i._children)
                        else:
                            tmp.append(i)
            if tmp:
                results.append(Branch(children=tmp, set_parents=False))
        return Queryable(results)

    def _crumbs_up(self):
        res = set()
        for c in self._children:
            segments = []
            cur = c
            while cur is not None:
                name = cur._name
                if name is not None:
                    segments.append(name)
                cur = cur._parent

            if len(segments) == 0:
                res.add("")
            elif len(segments) == 1:
                res.add(segments[0])
            else:
                segments = list(reversed(segments))
                path = [segments[0]]
                for r in segments[1:]:
                    r = "." + r if r.isidentifier() else '["{}"]'.format(r)
                    path.append(r)
                res.add("".join(path))
        return sorted(res)

    def _crumbs_down(self):
        res = set()

        def inner(node, base):
            try:
                for c in node._children:
                    name = c._name or ""
                    if base:
                        if not name.isidentifier():
                            name = '"{}"'.format(name)
                            path = base + "[" + name + "]"
                        else:
                            path = base + "." + name
                    else:
                        path = name
                    inner(c, path)
            except:
                res.add(base)

        for c in self._children:
            inner(c, "")
        return sorted(res)

    def crumbs(self, down=False):
        if down:
            return self._crumbs_down()
        return self._crumbs_up()

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

    def _get_nodes_of_type(self, Kind):
        res = []
        for node in self._children:
            try:
                for c in node._children:
                    if isinstance(c, Kind):
                        res.append(c)
            except:
                pass
        return Queryable(res)

    @property
    def branches(self):
        return self._get_nodes_of_type(Branch)

    @property
    def leaves(self):
        return self._get_nodes_of_type(Leaf)

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

    def _ipython_key_completions_(self):
        return self.keys()

    def __repr__(self):
        out = StringIO()
        for c in self._children:
            out.write(repr(c))
        contents = out.getvalue()
        out.close()
        return contents


def make_where_query(name, value=None):
    predicate = desugar(name) if value is None else desugar((name, value))

    # Optimization: where queries are regular predicates applied to all of a
    # nodes's children to see if it should be kept. Queryable.where passes the
    # children instead of the individual grandchildren like in Queryable.query.
    def inner(nodes):
        return any(predicate(n) for n in nodes)

    return pred(inner)


# typical alias
q = make_where_query


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

    return Queryable([Branch(name="conf", children=tuple(convert(raw)))])
