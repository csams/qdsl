from collections import Counter, defaultdict
from io import StringIO
from itertools import chain

from qdsl.boolean import Boolean, pred
from qdsl.tree import Branch, Leaf, flatten

# This is None for backward compat with a different lib.
# Ideally it would be ALL = object()
ALL = None


# Optimization: Special case queries where possible.
def _desugar(raw):
    """
    _desugar converts the raw query tuple into a regular function from Tree to
    Bool, optimizing special cases.

    Raw queries have two sub-queries, at least one of which must exist: a
    name query and one or more value queries. If there are two parts, they're
    in a tuple. The first element is the name query, and all remaining
    elements are value queries. The value queries are all "or'd", and the
    result is "anded" with the name query.
    """
    def desugar_name(query):
        if query is ALL:
            # Means match everything. If you want to match literal None, use eq(None).
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
        if query is ALL:
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

    # Here's is the main desugaring logic.
    if not isinstance(raw, tuple):
        # If the query isn't a tuple, we're just working on the name.
        predicate = desugar_name(raw)
    else:
        # It's a tuple, so there's a name query and at least one value query.
        namep = raw[0]
        valp = [desugar_value(q) for q in raw[1:]]
        if namep is ALL:
            # if the name query is ALL, that means all names are accepted. We
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
        """
        Filters the children list of each node and flattens the result.

        For example, if we start with a set of queryable nodes, cur, then
        cur[query] should look at the children of _each node_ in cur
        and collect all of those that match the query.
        """
        results = []
        for node in nodes:
            try:
                results.extend(gc for gc in node._children if query(gc))
            except:
                pass
        return results

    def __getattr__(self, key):
        return self.__getitem__(key)

    def __getitem__(self, query):
        if isinstance(query, (int, slice)):
            if isinstance(query, int):
                return Queryable([self._children[query]])

            if isinstance(query, slice):
                return Queryable(self._children[query])

        query = _desugar(query)
        results = self._run_query(query, self._children)
        return Queryable(results)

    def keys(self):
        """ Sorted list of unique names of the current results. """
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
        """
        Search everywhere beneath the current results for matching nodes.
        Like current_results[q0][q1]... except the set of queries gets
        applied as if every node everywhere beneath current_results was
        current_results.
        """
        res = []
        queries = [_desugar(q) for q in queries]
        # Optimization: querying the entire flattened tree at once is equivalent to querying individual nodes.
        for c in self._children:
            cur = list(flatten(c))
            for q in queries:
                if cur:
                    cur = self._run_query(q, cur)
            if cur:
                res.extend(cur)
        return Queryable(res)

    # Optimization: simplify the where API so we don't need a separate
    # WhereBoolean hierarchy. Where queries must be either a lambda or a
    # combination of "q(..)" instances.
    def where(self, query):
        """ Filter the current results based on properties of their children. """
        res = []
        if callable(query):
            # it's a lambda
            for c in self._children:
                try:
                    # give lambdas the Queryable API for each node.
                    # Do this manually instead of relying on __iter__ since
                    # we want to accumulate the original nodes, and this way
                    # is faster than digging them back out of the Queryables
                    # __iter__ would return.
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
        """ Query up the tree from the current results. """
        query = _desugar(query)
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
        """
        Orders the current result set based on values returned by a lambda.

        Example:

            # get the Config resources and see their conditions ordered by lastUpdateTime
            cfg = conf.where(q("kind", "Config"))
            res = cfg.status.conditions.where(q("status", "True")).order_by(lambda c: c.lastUpdateTime)
        """
        def predicate(node):
            res = selector(node)
            if isinstance(res, (list, tuple)):
                return [r.values for r in res]
            return res.values

        res = []
        for r in sorted(self, key=predicate, reverse=reverse):
            res.extend(r._children)
        return Queryable(res)

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
                        try:
                            for i in v._children:
                                if i._name is None:
                                    tmp.extend(i._children)
                                else:
                                    if isinstance(i, Branch):
                                        tmp.append(Branch(k, i._value, i._children, set_parents=False))
                                    else:
                                        tmp.append(Leaf(k, i._value))
                        except:
                            tmp.append(Leaf(k, (v,)))
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
        """
        See all paths by name up or down the tree from the current results.
        """
        if down:
            return self._crumbs_down()
        return self._crumbs_up()

    @property
    def parents(self):
        """ Get unique parent nodes of current results. """
        res = []
        seen = set()
        for c in self._children:
            p = c._parent
            if p is not None and p not in seen:
                seen.add(p)
                res.append(p)
        return Queryable(res)

    @property
    def sources(self):
        seen = set()
        for c in self._children:
            seen.add(c.source)
        return sorted(seen)

    @property
    def roots(self):
        """ Get unique root nodes of current results. """
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
        """Convert children to pandas Dataframe. """
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

    def _sub(self, other):
        res = []
        if not other:
            return self

        left = defaultdict(list)
        for c in self._children:
            left[(c._name, c._value)].append(c)

        right = defaultdict(list)
        for c in other._children:
            right[(c._name, c._value)].append(c)

        for key in left.keys() - right.keys():
            res.extend(left[key])

        overlap = left.keys() & right.keys()
        for key in overlap:
            for l in left[key]:
                diffs = []
                for r in right[key]:
                    try:
                        diff = Queryable(l._children)._sub(Queryable(r._children))
                        diffs.append(diff)
                        if not diff:
                            break
                    except:
                        pass
                try:
                    res.extend(sorted(diffs, key=len)[0])
                except:
                    pass
        return res

    def __sub__(self, other):
        res = self._sub(other)
        return Queryable([Branch(children=res, set_parents=False)])

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
    query = name if value is None else (name, value)
    predicate = _desugar(query)

    # Optimization: where queries are regular predicates applied to all of a
    # nodes's children to see if it should be kept. Queryable.where passes the
    # list of children instead of the individual grandchildren like in
    # Queryable.query.
    def inner(nodes):
        return any(predicate(n) for n in nodes)

    return pred(inner)


# typical alias for creating where queries.
q = make_where_query


# Optimization: use tuples instead of lists for values and children.
def to_queryable(raw, root_name="conf", source=None):
    """
    Generic data is made of dictionaries, lists, and primitives. Assume lists
    contain only dictionaries or primitives. If the value side of a dict key
    is a list and the list is full of primitives, a Leaf is generated with
    the dict key as its name and the list as its value. If the list contains
    dicts, a Branch is generated for each one, and each Branch is named by
    the original dict key. Nested lists are recursively flattened.
    """
    def convert(data):
        results = []
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    results.append(Branch(k, children=tuple(convert(v))))
                elif isinstance(v, list):
                    if v:
                        # Assume all list values have the same shape (list, dict, or primitive).
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

    return Queryable([Branch(name=root_name, children=tuple(convert(raw)), source=source)])
