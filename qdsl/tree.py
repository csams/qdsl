"""
Branch and Leaf are the data structures that Queryable provides a DSL over.
"""
import re
import sys
from io import StringIO

# intern is a builtin til python3
try:
    intern = sys.intern
except:
    pass


class Tree(object):
    # Optimization: use slots
    __slots__ = ["_name", "_value", "_parent", "_source"]

    def __init__(self, name, value, source=None):
        # Optimization: intern node names. This is especially effective
        # for k8s/openshift resources.
        self._name = intern(name) if name is not None else name
        self._value = value
        self._parent = None
        self._source = source

    @property
    def source(self):
        """
        the object (eg filename, url, etc.) that is the "source" of this tree
        """
        cur = self
        while cur is not None:
            src = cur._source
            if src is not None:
                return src
            cur = cur._parent

    def __repr__(self):
        out = StringIO()
        write = out.write

        def inner(node, indent=""):
            value = " ".join("{!r}".format(v) for v in node._value)
            if isinstance(node, Branch):
                txt = f"{node._name} {value}".strip()
                write(f"\n{indent}[{txt}]\n")
                new_indent = "  " + indent
                for child in node._children:
                    inner(child, indent=new_indent)
                write("\n")
            else:
                txt = f"{node._name}: {value}".strip()
                write(f"{indent}{txt}\n")

        inner(self)
        contents = re.sub("\n\n\n*", "\n\n", out.getvalue(), flags=re.MULTILINE)
        out.close()
        return contents


class Branch(Tree):
    """
    Branch represents a named section that may have values and/or
    children.
    """
    # Optimization: use slots
    __slots__ = ["_children"]

    # Optimization: "value" defaults to an empty tuple. It's immutable, and
    # since it's a keyword default value, all Branch instances share the same
    # one.
    def __init__(self, name=None, value=(), children=None, set_parents=True, **kwargs):
        super().__init__(name, value, **kwargs)
        self._children = children if children is not None else ()
        if set_parents:
            for c in self._children:
                c._parent = self


class Leaf(Tree):
    """ Leaf represents simple name/value pairs. """
    def __init__(self, name=None, value=None, **kwargs):
        super().__init__(name, value, **kwargs)


def flatten(node):
    """ Yields every tree node in a top down, depth first fashion. """
    yield node
    try:
        for c in node._children:
            yield from flatten(c)
    except:
        pass
