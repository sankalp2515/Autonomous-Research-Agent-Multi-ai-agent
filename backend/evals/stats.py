"""Small, dependency-free statistics shared by the eval harnesses.

Every rate an eval publishes carries its denominator and a 95% interval. A bare
"0 false accepts" on 12 cases and on 1,200 cases are different claims, and a
reader cannot tell them apart without the n and the interval. The Wilson score
interval is used because it stays inside [0, 1] and behaves at 0 and n, which
the normal approximation does not (it reports [0, 0] for 0/12).
"""

from math import sqrt

Z95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    # At k=0 / k=n the bound is exactly 0 / 1; float error would print 2.8e-17.
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return (lo, hi)


def rate(successes: int, n: int) -> dict:
    """A proportion as the eval suites publish it: count, n, point, interval."""
    lo, hi = wilson(successes, n)
    return {
        "k": successes, "n": n,
        "rate": round(successes / n, 4) if n else None,
        "ci95": [round(lo, 4), round(hi, 4)],
    }


def fmt(r: dict) -> str:
    """'4/71 = 5.6% [2.2%, 13.6%]' — or 'n/a (n=0)' when nothing was measured."""
    if not r.get("n"):
        return "n/a (n=0)"
    lo, hi = r["ci95"]
    return f"{r['k']}/{r['n']} = {r['rate']:.1%} [{lo:.1%}, {hi:.1%}]"
