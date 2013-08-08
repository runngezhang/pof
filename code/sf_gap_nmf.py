"""
Source-filter dictionary prior GaP-NMF

CREATED: 2013-07-25 15:09:04 by Dawen Liang <daliang@adobe.com>

"""

import numpy as np
from math import log

import gap_nmf
import _gap

import scipy.special as special
import scipy.optimize as optimize


class SF_GaP_NMF(gap_nmf.GaP_NMF):
    def __init__(self, X, U, gamma, alpha, K=100, smoothness=100,
                 seed=None, **kwargs):
        self.X = X.copy()
        self.K = K
        self.U = U.copy()
        self.alpha = alpha.copy()
        self.gamma = gamma.copy()
        # check if gamma is in the shape of (F, 1) for broadcasting with (F, K)
        if self.gamma.ndim == 1:
            self.gamma = self.gamma[:, np.newaxis]

        self.F, self.T = X.shape
        self.L = alpha.size

        if seed is None:
            print 'Using random seed'
        else:
            print 'Using fixed seed {}'.format(seed)

        self._parse_args(**kwargs)
        self._init(smoothness)

    def _parse_args(self, **kwargs):
        self.b = kwargs['b'] if 'b' in kwargs else 0.1
        self.beta = kwargs['beta'] if 'beta' in kwargs else 1.

    def _init(self, smoothness):
        self.rhow = 10000 * np.random.gamma(smoothness,
                                            1. / smoothness,
                                            size=(self.F, self.K))
        self.tauw = 10000 * np.random.gamma(smoothness,
                                            1. / smoothness,
                                            size=(self.F, self.K))
        self.rhoh = 10000 * np.random.gamma(smoothness,
                                            1. / smoothness,
                                            size=(self.K, self.T))
        self.tauh = 10000 * np.random.gamma(smoothness,
                                            1. / smoothness,
                                            size=(self.K, self.T))
        self.rhot = self.K * 10000 * np.random.gamma(smoothness,
                                                     1. / smoothness,
                                                     size=(self.K, ))
        self.taut = 1. / self.K * 10000 * np.random.gamma(smoothness,
                                                          1. / smoothness,
                                                          size=(self.K, ))
        self.nua = 10000 * np.random.gamma(smoothness,
                                           1. / smoothness,
                                           size=(self.L, self.K))
        self.rhoa = 10000 * np.random.gamma(smoothness,
                                            1. / smoothness,
                                            size=(self.L, self.K))
        self.compute_expectations()
        self.logEexpa = np.zeros((self.F, self.L, self.K))

    def compute_expectations(self):
        self.Ew, self.Ewinv = _gap.compute_gig_expectations(self.gamma,
                                                            self.rhow,
                                                            self.tauw)
        self.Ewinvinv = 1. / self.Ewinv
        self.Eh, self.Ehinv = _gap.compute_gig_expectations(self.b,
                                                            self.rhoh,
                                                            self.tauh)
        self.Ehinvinv = 1. / self.Ehinv
        self.Et, self.Etinv = _gap.compute_gig_expectations(self.beta / self.K,
                                                            self.rhot,
                                                            self.taut)
        self.Etinvinv = 1. / self.Etinv
        self.Ea, self.Eloga = _gap.compute_gamma_expectation(self.nua,
                                                             self.rhoa)

    def update(self, disp=0):
        ''' Do optimization for one iteration
        '''
        self.update_h()
        #goodk, _ = self.goodk()
        goodk = self.goodk()
        for k in goodk:
            self.update_a(k, disp)
        self.update_w()
        self.update_theta()
        # truncate unused components
        self.clear_badk()

    def update_a(self, k, disp):
        def f(theta):
            nu, rho = np.exp(theta[:self.L]), np.exp(theta[-self.L:])
            Ea, Eloga = _gap.compute_gamma_expectation(nu, rho)
            # E[p(W|a)] + E[p(a)] - E[q(a)], collect terms by sufficient
            # statistics
            val = np.sum((self.alpha - nu) * Eloga)
            val = val - np.sum((self.alpha - rho) * Ea)
            val = val + np.sum(special.gammaln(nu) - nu * np.log(rho))

            logEexp = _gap.comp_log_exp(nu, rho, self.U)
            val = val - np.sum(self.gamma.ravel() * (self.Ew[:, k] *
                               np.exp(np.sum(logEexp, axis=1)) +
                               np.dot(self.U, Ea)))
            return -val

        def df(theta):
            nu, rho = np.exp(theta[:self.L]), np.exp(theta[-self.L:])
            logEexp = _gap.comp_log_exp(nu, rho, self.U)

            tmp = self.U / rho
            log_term, inv_term = np.empty_like(tmp), np.empty_like(tmp)
            idx = (tmp > -1)
            # log(1 + x) is better approximated as x if x is sufficiently small
            idx_dir = np.logical_and(idx, np.abs(tmp) > 1e-12)
            idx_app = (np.abs(tmp) <= 1e-12)
            log_term[idx_dir] = np.log(1. + tmp[idx_dir])
            log_term[idx_app] = tmp[idx_app]
            log_term[-idx] = -np.inf
            inv_term[idx], inv_term[-idx] = 1. / (1. + tmp[idx]), np.inf

            grad_nu = np.sum((self.Ew[:, k, np.newaxis] * log_term *
                              np.exp(np.sum(logEexp, axis=1, keepdims=True))
                              - self.U / rho) * self.gamma, axis=0)
            grad_nu = grad_nu + 1 - self.alpha / rho
            grad_nu = grad_nu + (self.alpha - nu) * special.polygamma(1, nu)

            grad_rho = np.sum((self.U - self.Ew[:, k, np.newaxis] *
                               self.U * inv_term *
                               np.exp(np.sum(logEexp, axis=1, keepdims=True)))
                              * self.gamma, axis=0)
            grad_rho = nu / rho**2 * grad_rho
            grad_rho = grad_rho + self.alpha * (nu / rho**2 - 1. / rho)
            return -np.hstack((nu * grad_nu, rho * grad_rho))

        theta0 = np.hstack((np.log(self.nua[:, k]), np.log(self.rhoa[:, k])))
        theta_hat, _, d = optimize.fmin_l_bfgs_b(f, theta0, fprime=df, disp=0)
        if disp and d['warnflag']:
            if d['warnflag'] == 2:
                print 'A[:, {}]: {}, f={}'.format(k, d['task'],
                                                  f(theta_hat))
            else:
                print 'A[:, {}]: {}, f={}'.format(k, d['warnflag'],
                                                  f(theta_hat))
            app_grad = approx_grad(f, theta_hat)
            ana_grad = df(theta_hat)
            for l in xrange(self.L):
                if abs(ana_grad[l] - app_grad[l]) > .1:
                    print_gradient('log_a[{}, {:3d}]'.format(l, k),
                                   theta_hat[l], ana_grad[l], app_grad[l])
                    print_gradient('log_b[{}, {:3d}]'.format(l, k),
                                   theta_hat[l + self.L], ana_grad[l + self.L],
                                   app_grad[l + self.L])

        self.nua[:, k], self.rhoa[:, k] = np.exp(theta_hat[:self.L]), np.exp(
            theta_hat[-self.L:])
        assert(np.all(self.nua[:, k] > 0))
        assert(np.all(self.rhoa[:, k] > 0))
        self.Ea[:, k], self.Eloga[:, k] = _gap.compute_gamma_expectation(
            self.nua[:, k], self.rhoa[:, k])
        self.logEexpa[:, :, k] = _gap.comp_log_exp(self.nua[:, k],
                                                   self.rhoa[:, k],
                                                   self.U)

    def update_w(self):
        #goodk, c = self.goodk()
        goodk = self.goodk()
        xtwid = self._xtwid(goodk)
        c = np.mean(self.X / xtwid)
        print('Optimal scale for updating W: {}'.format(c))
        xxtwidinvsq = self.X / c * xtwid**(-2)
        xbarinv = 1. / self._xbar(goodk)
        dEt = self.Et[goodk]
        dEtinvinv = self.Etinvinv[goodk]

        self.rhow[:, goodk] = self.gamma * np.exp(np.sum(
            self.logEexpa[:, :, goodk], axis=1))
        self.rhow[:, goodk] = self.rhow[:, goodk] + np.dot(
            xbarinv, dEt * self.Eh[goodk, :].T)
        self.tauw[:, goodk] = self.Ewinvinv[:, goodk]**2 * \
                np.dot(xxtwidinvsq, dEtinvinv * self.Ehinvinv[goodk, :].T)
        self.tauw[self.tauw < 1e-100] = 0

        self.Ew[:, goodk], self.Ewinv[:, goodk] = _gap.compute_gig_expectations(
            self.gamma,
            self.rhow[:, goodk],
            self.tauw[:, goodk])

        if np.any(np.isnan(self.Ew)):
            dg = self.gamma * np.ones_like(self.rhow)
            print dg[np.isnan(self.Ew)]
            print self.rhow[np.isnan(self.Ew)]
            print self.tauw[np.isnan(self.Ew)]
        self.Ewinvinv[:, goodk] = 1. / self.Ewinv[:, goodk]

    def update_h(self):
        #goodk, c = self.goodk()
        goodk = self.goodk()
        xtwid = self._xtwid(goodk)
        c = np.mean(self.X / xtwid)
        print('Optimal scale for updating H: {}'.format(c))
        xxtwidinvsq = self.X / c * xtwid**(-2)
        xbarinv = 1. / self._xbar(goodk)
        dEt = self.Et[goodk]
        dEtinvinv = self.Etinvinv[goodk]
        self.rhoh[goodk, :] = self.b + np.dot(dEt[:, np.newaxis] *
                                              self.Ew[:, goodk].T,
                                              xbarinv)
        self.tauh[goodk, :] = self.Ehinvinv[goodk, :]**2 * \
                np.dot(dEtinvinv[:, np.newaxis] * self.Ewinvinv[:, goodk].T,
                        xxtwidinvsq)
        self.tauh[self.tauh < 1e-100] = 0
        self.Eh[goodk, :], self.Ehinv[goodk, :] = _gap.compute_gig_expectations(
            self.b,
            self.rhoh[goodk, :],
            self.tauh[goodk, :])
        self.Ehinvinv[goodk, :] = 1. / self.Ehinv[goodk, :]

    def update_theta(self):
        #goodk, c = self.goodk()
        goodk = self.goodk()
        xtwid = self._xbar(goodk)
        c = np.mean(self.X / xtwid)
        print('Optimal scale for updating theta: {}'.format(c))
        xxtwidinvsq = self.X / c * xtwid**(-2)
        xbarinv = 1. / self._xbar(goodk)
        self.rhot[goodk] = self.beta + np.sum(np.dot(
            self.Ew[:, goodk].T, xbarinv) *
            self.Eh[goodk, :], axis=1)
        self.taut[goodk] = self.Etinvinv[goodk]**2 * \
                np.sum(np.dot(self.Ewinvinv[:, goodk].T, xxtwidinvsq) *
                       self.Ehinvinv[goodk, :], axis=1)
        self.taut[self.taut < 1e-100] = 0
        self.Et[goodk], self.Etinv[goodk] = _gap.compute_gig_expectations(
            self.beta / self.K, self.rhot[goodk], self.taut[goodk])
        self.Etinvinv[goodk] = 1. / self.Etinv[goodk]

    def goodk(self, cut_off=1e-6):
        #c = np.mean(self.X / self._xtwid())
        #cut_off = 1e-10 * np.amax(self.X / c)

        #powers = self.Et * np.amax(self.Ew, axis=0) * np.amax(self.Eh, axis=1)
        #sorted = np.flipud(np.argsort(powers))
        #idx = np.where(powers[sorted] > cut_off * np.amax(powers))[0]
        #goodk = sorted[:(idx[-1] + 1)]
        #if powers[goodk[-1]] < cut_off:
        #    goodk = np.delete(goodk, -1)
        #return goodk
        sorted = np.flipud(np.argsort(self.Et))
        idx = np.where(self.Et[sorted] > cut_off * np.sum(self.Et))[0]
        goodk = sorted[:(idx[-1] + 1)]
        return goodk

    def clear_badk(self):
        ''' Set unsued components' posteriors equal to their priors
        '''
        #goodk, _ = self.goodk()
        goodk = self.goodk()
        badk = np.setdiff1d(np.arange(self.K), goodk)
        self.rhow[:, badk] = self.gamma
        self.tauw[:, badk] = 0
        self.rhoh[badk, :] = self.b
        self.tauh[badk, :] = 0
        self.nua[:, badk] = self.alpha[:, np.newaxis]
        self.rhoa[:, badk] = self.alpha[:, np.newaxis]
        self.compute_expectations()
        self.logEexpa[:, :, badk] = 0

    def bound(self):
        score = 0
        #goodk, c = self.goodk()
        goodk = self.goodk()
        c = np.mean(self.X / self._xtwid(goodk))
        xbar = self._xbar(goodk)

        score = score - np.sum(np.log(xbar) + log(c))
        score = score + _gap.gig_gamma_term(self.Ew, self.Ewinv, self.rhow,
                                            self.tauw, self.gamma, self.gamma *
                                            np.exp(np.sum(self.logEexpa,
                                                          axis=1)))
        score = score + _gap.gig_gamma_term(self.Eh, self.Ehinv, self.rhoh,
                                            self.tauh, self.b, self.b)
        score = score + _gap.gig_gamma_term(self.Et, self.Etinv, self.rhot,
                                            self.taut, self.beta / self.K,
                                            self.beta)
        score = score + _gap.gamma_term(self.Ea, self.Eloga, self.nua,
                                        self.rhoa, self.alpha)
        return score

    def _xbar(self, goodk=None):
        if goodk is None:
            goodk = np.arange(self.K)
        return np.dot(self.Ew[:, goodk] * self.Et[goodk],
                      self.Eh[goodk, :])

    def _xtwid(self, goodk=None):
        if goodk is None:
            goodk = np.arange(self.K)
    #def _xtwid(self, goodk):
        return np.dot(self.Ewinvinv[:, goodk] * self.Etinvinv[goodk],
                      self.Ehinvinv[goodk, :])


def approx_grad(f, x, delta=1e-8, args=()):
    x = np.asarray(x).ravel()
    grad = np.zeros_like(x)
    diff = delta * np.eye(x.size)
    for i in xrange(x.size):
        grad[i] = (f(x + diff[i], *args) - f(x - diff[i], *args)) / (2 * delta)
    return grad


def print_gradient(name, val, grad, approx):
    print('{} = {:.2f}\tGradient: {:.2f}\tApprox: {:.2f}\t'
          '| Diff |: {:.3f}'.format(name, val, grad, approx,
                                    np.abs(grad - approx)))


def entropy(alpha, beta):
    ''' Compute the entropy of a r.v. theta ~ Gamma(alpha, beta)
    '''
    return (alpha - np.log(beta) + special.gammaln(alpha) +
            (1 - alpha) * special.psi(alpha))
