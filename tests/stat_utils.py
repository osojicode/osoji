"""Statistical utilities for prompt regression tests.

Provides a one-sided binomial test framework to detect regressions in
stochastic LLM-based tests with controlled false-positive rates.
"""

from scipy.stats import binom, binomtest


def compute_sample_size(p0: float) -> int:
    """Compute minimum N for one-sided binomial test.

    Finds smallest N such that if true p = p0, we reject
    H0: p <= p0*(1-relative_drop) with probability >= power.

    Tuning: 1% false failure rate (alpha), 1% miss rate (power),
    detects 40% regression. N typically 10-68 trials.
    """
    relative_drop = 0.4
    alpha = 0.01
    power = 0.99
    max_n = 70
    threshold = p0 * (1 - relative_drop)
    for n in range(5, max_n + 1):
        # If true p = p0, what's P(reject H0)?
        # = sum over k of P(X=k|p0) * I(binomtest(k,n,threshold) rejects)
        reject_prob = 0.0
        for k in range(n + 1):
            p_k = binom.pmf(k, n, p0)
            result = binomtest(k, n, threshold, alternative="greater")
            if result.pvalue < alpha:
                reject_prob += p_k
        if reject_prob >= power:
            return n
    return max_n


def assert_pass_rate(k: int, n: int, p0: float) -> None:
    """Assert observed k/n passes is consistent with p >= threshold.

    Raises AssertionError with diagnostic message if we cannot reject
    H0: p <= p0*(1-relative_drop) at the given alpha level.
    """
    relative_drop = 0.4
    alpha = 0.01
    threshold = p0 * (1 - relative_drop)
    result = binomtest(k, n, threshold, alternative="greater")
    if result.pvalue >= alpha:
        ci_low = result.proportion_ci(confidence_level=1 - alpha).low
        raise AssertionError(
            f"Statistical regression detected: {k}/{n} passed "
            f"(observed {k/n:.1%}, baseline p0={p0:.1%}, "
            f"threshold={threshold:.1%}, p-value={result.pvalue:.3f}, "
            f"CI lower bound={ci_low:.1%})"
        )
