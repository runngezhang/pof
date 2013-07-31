"""
Utils for GaP-NMF

CREATED: 2013-07-23 14:20:10 by Dawen Liang <daliang@adobe.com>

"""

import numpy as np
import scipy.special as special

from math import log


def compute_gig_expectations(alpha, beta, gamma):
    alpha = alpha * np.ones_like(beta)

    Ex, Exinv = np.zeros_like(beta), np.zeros_like(beta)

    # For very small values of gamma and positive values of alpha, the GIG
    # distribution becomes a gamma distribution, and its expectations are both
    # cheaper and more stable to compute that way.
    gig_inds = (gamma > 1e-200)
    gam_inds = (gamma <= 1e-200)

    if np.any(alpha[gam_inds] < 0):
        raise ValueError("problem with arguments.")

    # Compute expectations for GIG distribution.
    sqrt_beta = np.sqrt(beta[gig_inds])
    sqrt_gamma = np.sqrt(gamma[gig_inds])
    # Note that we're using the *scaled* version here, since we're just
    # computing ratios and it's more stable.
    bessel_alpha_minus = special.kve(alpha[gig_inds] - 1, 2 * sqrt_beta *
                                     sqrt_gamma)
    bessel_alpha = special.kve(alpha[gig_inds], 2 * sqrt_beta * sqrt_gamma)
    bessel_alpha_plus = special.kve(alpha[gig_inds] + 1, 2 * sqrt_beta *
                                    sqrt_gamma)
    sqrt_ratio = sqrt_gamma / sqrt_beta

    Ex[gig_inds] = bessel_alpha_plus * sqrt_ratio / bessel_alpha
    Exinv[gig_inds] = bessel_alpha_minus / (sqrt_ratio * bessel_alpha)

    # Compute expectations for gamma distribution where we can get away with
    # it.
    Ex[gam_inds] = alpha[gam_inds] / beta[gam_inds]
    Exinv[gam_inds] = beta[gam_inds] / (alpha[gam_inds] - 1)
    Exinv[Exinv < 0] = np.inf

    return (Ex, Exinv)


def compute_gamma_expectation(alpha, beta):
    return (alpha / beta, special.psi(alpha) - np.log(beta))


def comp_log_exp(alpha, beta, U):
    ''' Compute log(E[exp(-au)]) where a ~ Gamma(alpha, beta) and u as a
    constant:
        log(E[exp(-au)]) = -alpha * log(1 + u / beta)
    '''
    tmp = U / beta
    log_exp = np.empty_like(tmp)
    idx = (tmp > -1)
    # log(1 + x) is better approximated as x if x is sufficiently small
    # otherwise, it can be directly computed
    idx_dir = np.logical_and(idx, np.abs(tmp) > 1e-12)
    idx_app = (np.abs(tmp) <= 1e-12)
    log_exp[idx_dir] = (-alpha * np.log(1. + tmp))[idx_dir]
    log_exp[idx_app] = (-alpha * tmp)[idx_app]
    log_exp[-idx] = np.inf
    return log_exp


def gig_gamma_term(Ex, Exinv, rho, tau, a, b):
    ''' Compute E_q[log p(x)] - E_q[log q(x)] where:
        p(x) = Gamma(a, b), q(x) = GIG(a, rho, tau)
    '''
    score = 0
    cut_off = 1e-200
    zero_tau = (tau <= cut_off)
    non_zero_tau = (tau > cut_off)
    if np.asarray(a).size == 1:
        score = score + Ex.size * (a * log(b) - special.gammaln(a))
    else:
        # shape(a) = (F, )  shape(b) = (F, K)
        score = score + np.sum(a * np.log(b) - special.gammaln(a))
    score = score - np.sum((b - rho) * Ex)

    score = score - np.sum(non_zero_tau) * log(.5)
    score = score + np.sum(tau[non_zero_tau] * Exinv[non_zero_tau])
    score = score - .5 * np.sum(a * (np.log(rho[non_zero_tau]) -
                                     np.log(tau[non_zero_tau])))
    # It's numerically safer to use scaled version of besselk
    score = score + np.sum(np.log(special.kve(
        a, 2 * np.sqrt(rho[non_zero_tau] * tau[non_zero_tau]))) -
        2 * np.sqrt(rho[non_zero_tau] * tau[non_zero_tau]))

    score = score + np.sum(-a * np.log(rho[zero_tau]) + special.gammaln(a))
    return score


def gamma_term(Ex, Elogx, nu, rho, a):
    ''' Compute E_q[log p(x)] - E_q [log q(x)] where:
        p(x) = Gamma(a, a), q(x) = Gamma(nu, rho)
    '''
    score = 0
    ca = a[:, np.newaxis]
    score = score + np.sum((ca - nu) * Elogx)
    score = score - np.sum((ca - rho) * Ex)
    score = score + np.sum(special.gammaln(nu) - special.gammaln(ca))
    score = score + np.sum(ca * np.log(ca) - nu * np.log(rho))
    return score
