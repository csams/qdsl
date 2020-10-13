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
    __slots__ = ["_name", "_value", "_parent"]

    def __init__(self, name, value):
        # Optimization: intern node names
        self._name = intern(name) if name is not None else name
        self._value = value
        self._parent = None

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
    # Optimization: use slots
    __slots__ = ["_children"]

    # Optimization: "value" defaults to an empty tuple. Since it's a
    # default keyword value, they'll all share the same one.
    def __init__(self, name=None, value=(), children=None, set_parents=True):
        super().__init__(name, value)
        self._children = children if children is not None else ()
        if set_parents:
            for c in self._children:
                c._parent = self


class Leaf(Tree):
    def __init__(self, name=None, value=None):
        super().__init__(name, value)


def flatten(node):
    yield node
    try:
        for c in node._children:
            yield from flatten(c)
    except:
        pass
