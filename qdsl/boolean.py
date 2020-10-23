"""
The boolean module lets you create complicated boolean expressions by composing
objects. The compositions can be evaluated against multiple values.
"""
import logging
import operator
import re

from functools import partial, wraps
from itertools import count

log = logging.getLogger(__name__)

__all__ = [
    "pred",
    "pred2",
    "flip",
    "TRUE",
    "FALSE",
    "flip",
    "pred",
    "pred2",
    "lt",
    "le",
    "eq",
    "ge",
    "gt",
    "isin",
    "contains",
    "search",
    "matches",
    "startswith",
    "endswith",
]


class Boolean:
    def test(self, value):
        raise NotImplementedError()

    def __and__(self, other):
        return All(self, other)

    def __or__(self, other):
        return Any(self, other)

    def __invert__(self):
        return Not(self)

    # Optimization: generate regular python functions from the AST.
    # This "compilation" takes microseconds.
    def to_pyfunc(self):
        env = {
            "log": log,
            "logging": logging
        }
        ids = count()

        def expr(b):
            if isinstance(b, All):
                return "(" + " and ".join(expr(p) for p in b.predicates) + ")"
            elif isinstance(b, Any):
                return "(" + " or ".join(expr(p) for p in b.predicates) + ")"
            elif isinstance(b, Not):
                return "(" + "not " + expr(b.predicate) + ")"
            elif isinstance(b, Predicate):
                num = next(ids)

                func = f"func_{num}"
                args = f"args_{num}"
                kwargs = f"kwargs_{num}"

                env[func] = b.predicate
                env[args] = b.args
                env[kwargs] = b.kwargs

                return func + "(value, " + "*" + args + ", **" + kwargs + ")"

        func = f"""
def predicate(value):
    try:
        return {expr(self)}
    except Exception as ex:
        if log.isEnabledFor(logging.DEBUG):
            log.debug(ex)
        return False
        """

        if log.isEnabledFor(logging.DEBUG):
            log.debug(func)

        exec(func, env, env)
        return env["predicate"]


class Any(Boolean):
    def __init__(self, *predicates):
        self.predicates = predicates

    def test(self, value):
        return any(predicate.test(value) for predicate in self.predicates)


class All(Boolean):
    def __init__(self, *predicates):
        self.predicates = predicates

    def test(self, value):
        return all(predicate.test(value) for predicate in self.predicates)


class Not(Boolean):
    def __init__(self, predicate):
        self.predicate = predicate

    def test(self, value):
        return not self.predicate.test(value)


class Predicate(Boolean):
    """ Calls a function to determine truth value. """

    def __init__(self, predicate, *args, **kwargs):
        self.predicate = predicate
        self.args = args
        self.kwargs = kwargs

    def test(self, value):
        try:
            return self.predicate(value, *self.args, **self.kwargs)
        except Exception as ex:
            if log.isEnabledFor(logging.DEBUG):
                log.debug(ex)
            return False


pred = Predicate


def pred2(predicate, *args, **kwargs):
    return partial(Predicate, predicate)


def flip(f):
    """
    Switches position of the first two arguments to f and ensures
    its result is a bool.
    """

    @wraps(f)
    def inner(a, b, *args, **kwargs):
        return bool(f(b, a, *args, **kwargs))

    return inner


class TRUE(Boolean):
    def test(self, value):
        return True


class FALSE(Boolean):
    def test(self, value):
        return False


TRUE = TRUE()
FALSE = FALSE()

lt = pred2(operator.lt)
le = pred2(operator.le)
eq = pred2(operator.eq)
ge = pred2(operator.ge)
gt = pred2(operator.gt)

isin = pred2(flip(operator.contains))

contains = pred2(operator.contains)
search = pred2(flip(re.search))
matches = search
startswith = pred2(str.startswith)
endswith = pred2(str.endswith)
