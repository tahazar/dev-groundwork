import numpy as np
from lib import Foo


def caller(xs):
    Foo(1)
    return np.mean(xs)
