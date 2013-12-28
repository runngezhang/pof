"""

Source-filter dictionary prior learning for gamma noise model

CREATED: 2013-07-12 11:09:44 by Dawen Liang <daliang@adobe.com>

"""

import time
import sys

import numpy as np
import scipy.optimize as optimize
import scipy.special as special

class SF_Dict(object):
    def __init__(self, W, L=10, smoothness=100, seed=None):
        self.W = W.copy()
        self.T, self.F = W.shape
        self.L = L
        if seed is None:
            print 'Using random seed'
            np.random.seed()
        else:
            print 'Using fixed seed {}'.format(seed)
            np.random.seed(seed)
        self._init(smoothness)
        self._init_variational(smoothness)

    def _init(self, smoothness):
        # model parameters
        self.U = np.random.randn(self.L, self.F)
        self.alpha = np.random.gamma(smoothness,
                                     1. / smoothness,
                                     size=(self.L,))
        self.gamma = np.random.gamma(smoothness,
                                     1. / smoothness,
                                     size=(self.F,))

    def _init_variational(self, smoothness):
        self.a = smoothness * np.random.gamma(smoothness,
                                              1. / smoothness,
                                              size=(self.T, self.L))
        self.b = smoothness * np.random.gamma(smoothness,
                                              1. / smoothness,
                                              size=(self.T, self.L))
        self.EA, self.ElogA = comp_expect(self.a, self.b)

    def vb_e(self, cold_start=True, smoothness=100, maxiter=15000,
             verbose=True, disp=0):
        """ Perform one variational E-step to appxorimate the posterior
        P(A | -)

        Parameters
        ----------
        cold_start: bool
            Do e-step with fresh start, otherwise just do e-step with
            previous values as initialization.
        smoothness: float
            Smootheness of the variational initialization, larger value will
            lead to more concentrated initialization.
        verbose: bool
            Output log if true.
        disp: int
            Display warning from solver if > 0, mainly from LBFGS.

        """
        print 'Variational E-step...'
        if cold_start:
            # re-initialize all the variational parameters
            self._init_variational(smoothness)

        if verbose:
            last_score = self.bound()
            print('Update (initial)\tObj: {:.2f}'.format(last_score))
            start_t = time.time()
        for t in xrange(self.T):
            #last_score = self.bound()
            self.update_theta_batch(t, maxiter, disp)
            #score = self.bound()
            #if score < last_score:
            #    print('Oops, before: {}\tafter: {}\tt={}'.format(
            #        last_score, score, t))
            if verbose and not t % 100:
                sys.stdout.write('.')
        if verbose:
            t = time.time() - start_t
            sys.stdout.write('\n')
            print 'Batch update\ttime: {:.2f}'.format(t)
            score = self.bound()
            print_increment('A', last_score, score)

    def update_theta_batch(self, t, maxiter, disp):
        def f(theta):
            a, b = np.exp(theta[:self.L]), np.exp(theta[-self.L:])
            Ea, Eloga = comp_expect(a, b)
            logEexp = comp_log_exp(a[:, np.newaxis],
                                   b[:, np.newaxis], self.U)
            likeli = (-self.W[t] * np.exp(np.sum(logEexp, axis=0))
                      - np.dot(Ea, self.U)) * self.gamma
            prior = (self.alpha - 1) * Eloga - self.alpha * Ea
            ent = entropy(a, b)

            return -(likeli.sum() + prior.sum() + ent.sum())

        def df(theta):
            a, b = np.exp(theta[:self.L]), np.exp(theta[-self.L:])
            logEexp = comp_log_exp(a[:, np.newaxis],
                                   b[:, np.newaxis], self.U)

            tmp = self.U / b[:, np.newaxis]
            log_term, inv_term = np.empty_like(tmp), np.empty_like(tmp)
            idx = (tmp > -1)
            # log(1 + x) is better approximated as x if x is sufficiently small
            idx_dir = np.logical_and(idx, np.abs(tmp) > 1e-12)
            idx_app = (np.abs(tmp) <= 1e-12)
            log_term[idx_dir] = np.log(1. + tmp[idx_dir])
            log_term[idx_app] = tmp[idx_app]
            log_term[-idx] = -np.inf
            inv_term[idx], inv_term[-idx] = 1. / (1. + tmp[idx]), np.inf

            grad_a = np.sum(self.W[t] * log_term * np.exp(
                np.sum(logEexp, axis=0)) *
                self.gamma - self.U / b[:, np.newaxis] * self.gamma, axis=1)
            grad_a = grad_a + (self.alpha - a) * special.polygamma(1, a)
            grad_a = grad_a + 1 - self.alpha / b
            grad_b = a / b**2 * np.sum(-self.U * self.W[t] * inv_term *
                                       np.exp(np.sum(logEexp, axis=0)) *
                                       self.gamma + self.U * self.gamma,
                                       axis=1)
            grad_b = grad_b + self.alpha * (a / b**2 - 1. / b)
            return -np.hstack((a * grad_a, b * grad_b))

        theta0 = np.hstack((np.log(self.a[t]), np.log(self.b[t])))
        theta_hat, _, d = optimize.fmin_l_bfgs_b(f, theta0, fprime=df,
                                                 maxiter=maxiter, disp=0)
        if disp and d['warnflag']:
            if d['warnflag'] == 2:
                print 'A[{}, :]: {}, f={}'.format(t,
                                                  d['task'],
                                                  f(theta_hat))
            else:
                print 'A[{}, :]: {}, f={}'.format(t,
                                                  d['warnflag'],
                                                  f(theta_hat))
            app_grad = approx_grad(f, theta_hat)
            ana_grad = df(theta_hat)
            for l in xrange(self.L):
                print_gradient('log_a[{}, {:3d}]'.format(t, l),
                               theta_hat[l],
                               ana_grad[l],
                               app_grad[l])
                print_gradient('log_b[{}, {:3d}]'.format(t, l),
                               theta_hat[l + self.L],
                               ana_grad[l + self.L],
                               app_grad[l + self.L])

        self.a[t], self.b[t] = np.exp(theta_hat[:self.L]), np.exp(
            theta_hat[-self.L:])
        assert(np.all(self.a[t] > 0))
        assert(np.all(self.b[t] > 0))
        self.EA[t], self.ElogA[t] = comp_expect(self.a[t], self.b[t])

    def vb_m(self, batch=False, maxiter=15000, verbose=True, disp=0):
        """ Perform one M-step, update the model parameters with A fixed
        from E-step

        Parameters
        ----------
        batch: bool
            Update U as a whole optimization if true. Otherwise, update U
            across different basis.
        verbose: bool
            Output log if ture.
        disp: int
            Display warning from solver if > 0, mostly from LBFGS.
        update_alpha: bool
            Update alpha if true.

        """

        print 'Variational M-step...'
        if verbose:
            old_U = self.U.copy()
            old_gamma = self.gamma.copy()
            old_alpha = self.alpha.copy()
            last_score = self.bound()
            print('Update (initial)\tObj: {:.2f}'.format(last_score))
            start_t = time.time()
        if batch:
            for f in xrange(self.F):
                self.update_u_batch(f, maxiter, disp)
                #score = self.bound()
                #if score < last_score:
                #    print('Oops, before: {}\tafter: {}\tf={}'.format(
                #        last_score, score, f))
                #last_score = score
        else:
            for l in xrange(self.L):
                self.update_u(l, maxiter, disp)
                if verbose:
                    score = self.bound()
                    print_increment('U[{}]'.format(l), last_score, score)
                    last_score = score
        self.update_gamma(disp)
        if verbose:
            score = self.bound()
            print_increment('gamma', last_score, score)
            last_score = score

        self.update_alpha(disp)
        if verbose:
            score = self.bound()
            print_increment('alpha', last_score, score)

        if verbose:
            t = time.time() - start_t
            U_diff = np.mean(np.abs(self.U - old_U))
            sigma_diff = np.mean(np.abs(np.sqrt(1. / self.gamma) -
                                        np.sqrt(1. / old_gamma)))
            alpha_diff = np.mean(np.abs(self.alpha - old_alpha))
            print('U diff: {:.4f}\tsigma dff: {:.4f}\talpha diff: {:.4f}\t'
                  'time: {:.2f}'.format(U_diff, sigma_diff, alpha_diff, t))

    def update_u_batch(self, f, maxiter, disp):
        def fun(u):
            Eexp = np.exp(np.sum(comp_log_exp(self.a, self.b, u), axis=1))
            return np.sum(self.gamma[f] * (Eexp * self.W[:, f] +
                                           np.dot(self.EA, u)))

        def dfun(u):
            tmp = 1 + u / self.b
            inv_term = np.empty_like(tmp)
            idx = (tmp > 0)
            inv_term[idx], inv_term[-idx] = 1. / tmp[idx], np.inf
            Eexp = np.exp(np.sum(comp_log_exp(self.a, self.b, u), axis=1))
            return np.sum(self.EA * (1 - (self.W[:, f] * Eexp)[:, np.newaxis] *
                                     inv_term), axis=0)

        u0 = self.U[:, f]
        self.U[:, f], _, d = optimize.fmin_l_bfgs_b(fun, u0, fprime=dfun,
                                                    maxiter=maxiter, disp=0)
        if disp and d['warnflag']:
            if d['warnflag'] == 2:
                print 'U[:, {}]: {}, f={}'.format(f, d['task'],
                                                  fun(self.U[:, f]))
            else:
                print 'U[:, {}]: {}, f={}'.format(f, d['warnflag'],
                                                  fun(self.U[:, f]))
            app_grad = approx_grad(fun, self.U[:, f])
            ana_grad = dfun(self.U[:, f])
            for l in xrange(self.L):
                print_gradient('U[{}, {:3d}]'.format(l, f), self.U[l, f],
                               ana_grad[l], app_grad[l])

    def update_u(self, l, maxiter, disp):
        def f(u):
            Eexp = np.exp(comp_log_exp(self.a[:, l, np.newaxis],
                                       self.b[:, l, np.newaxis], u))
            return np.sum(np.outer(self.EA[:, l], u) + self.W * Eexp * Eres)

        def df(u):
            tmp = np.exp(comp_log_exp(self.a[:, l, np.newaxis] + 1.,
                                      self.b[:, l, np.newaxis], u))
            return np.sum(self.EA[:, l, np.newaxis] *
                          (1 - self.W * Eres * tmp), axis=0)

        k_idx = np.delete(np.arange(self.L), l)
        Eres = 0.
        for k in k_idx:
            Eres = Eres + comp_log_exp(self.a[:, k, np.newaxis],
                                       self.b[:, k, np.newaxis],
                                       self.U[k])
        Eres = np.exp(Eres)

        u0 = self.U[l]
        self.U[l], _, d = optimize.fmin_l_bfgs_b(f, u0, fprime=df,
                                                 maxiter=maxiter, disp=0)
        if disp and d['warnflag']:
            if d['warnflag'] == 2:
                print 'U[{}, :]: {}, f={}'.format(l, d['task'],
                                                  f(self.U[l]))
            else:
                print 'U[{}, :]: {}, f={}'.format(l, d['warnflag'],
                                                  f(self.U[l]))
            app_grad = approx_grad(f, self.U[l])
            ana_grad = df(self.U[l])
            for fr in xrange(self.F):
                print_gradient('U[{}, {:3d}]'.format(l, fr), self.U[l, fr],
                               ana_grad[fr], app_grad[fr])

    def update_gamma(self, disp):
        def f(eta):
            gamma = np.exp(eta)
            return -(self.T * np.sum(gamma * eta - special.gammaln(gamma)) +
                     np.sum(gamma * np.log(self.W) - gamma *
                            np.dot(self.EA, self.U) - gamma * self.W * Eexp))

        def df(eta):
            gamma = np.exp(eta)
            return -gamma * (self.T * (eta + 1 - special.psi(gamma)) +
                             np.sum(-np.dot(self.EA, self.U) +
                                    np.log(self.W) - self.W * Eexp, axis=0))

        Eexp = 0.
        for l in xrange(self.L):
            Eexp = Eexp + comp_log_exp(self.a[:, l, np.newaxis],
                                       self.b[:, l, np.newaxis],
                                       self.U[l])
        Eexp = np.exp(Eexp)

        eta0 = np.log(self.gamma)
        eta_hat, _, d = optimize.fmin_l_bfgs_b(f, eta0, fprime=df, disp=0)
        self.gamma = np.exp(eta_hat)
        if disp and d['warnflag']:
            if d['warnflag'] == 2:
                print 'f={}, {}'.format(f(eta_hat), d['task'])
            else:
                print 'f={}, {}'.format(f(eta_hat), d['warnflag'])
            app_grad = approx_grad(f, eta_hat)
            ana_grad = df(eta_hat)
            for idx in xrange(self.F):
                print_gradient('Gamma[{:3d}]'.format(idx), self.gamma[idx],
                               ana_grad[idx], app_grad[idx])

    def update_alpha(self, disp):
        def f(eta):
            tmp1 = np.exp(eta) * eta - special.gammaln(np.exp(eta))
            tmp2 = self.ElogA * (np.exp(eta) - 1) - self.EA * np.exp(eta)
            return -(self.T * tmp1.sum() + tmp2.sum())

        def df(eta):
            return -np.exp(eta) * (self.T * (eta + 1 -
                                             special.psi(np.exp(eta)))
                                   + np.sum(self.ElogA - self.EA, axis=0))

        eta0 = np.log(self.alpha)
        eta_hat, _, d = optimize.fmin_l_bfgs_b(f, eta0, fprime=df, disp=0)
        self.alpha = np.exp(eta_hat)
        if disp and d['warnflag']:
            if d['warnflag'] == 2:
                print 'f={}, {}'.format(f(eta_hat), d['task'])
            else:
                print 'f={}, {}'.format(f(eta_hat), d['warnflag'])
            app_grad = approx_grad(f, eta_hat)
            ana_grad = df(eta_hat)
            for l in xrange(self.L):
                print_gradient('Alpha[{:3d}]'.format(l), self.alpha[l],
                               ana_grad[l], app_grad[l])

    def bound(self):
        Eexp = 0.
        for l in xrange(self.L):
            Eexp = Eexp + comp_log_exp(self.a[:, l, np.newaxis],
                                       self.b[:, l, np.newaxis],
                                       self.U[l])
        Eexp = np.exp(Eexp)
        # E[log P(w|a)]
        bound = self.T * np.sum(self.gamma * np.log(self.gamma) -
                                special.gammaln(self.gamma))
        print bound
        bound = bound + np.sum(-self.gamma * np.dot(self.EA, self.U) +
                               (self.gamma - 1) * np.log(self.W) -
                               self.W * Eexp * self.gamma)
        print bound
        # E[log P(a)]
        bound = bound + self.T * np.sum(self.alpha * np.log(self.alpha) -
                                        special.gammaln(self.alpha))
        print bound
        bound = bound + np.sum(self.ElogA * (self.alpha - 1) -
                               self.EA * self.alpha)
        print bound
        # E[loq q(a)]
        bound = bound + np.sum(entropy(self.a, self.b))
        print bound
        return bound

    ## This function is deprecated
    #def comp_exp_expect(self, alpha, beta, U):
    #    ''' Compute E[exp(-au)] where a ~ Gamma(alpha, beta) and u constant

    #    This function makes extensive use of broadcasting, thus the dimension
    #    of input arguments can only be one of the following two situations:
    #         1) U has shape (L, F), alpha and beta have shape (L, 1)
    #            --> output shape (L, F)
    #         2) U has shape (F, ), alpha and beta have shape (T, 1)
    #            --> output shape (T, F)
    #    '''
    #    # using Taylor expansion for large alpha (hence beta) to more
    #    # accurately compute (1 + u/beta)**(-alpha)
    #    idx = np.logical_and(alpha < 1e10, beta < 1e10).ravel()
    #    if alpha.size == self.L:
    #        expect = np.empty_like(U)
    #        expect[idx] = (1 + U[idx] / beta[idx])**(-alpha[idx])
    #        expect[-idx] = np.exp(-U[-idx] * alpha[-idx] / beta[-idx])
    #    elif alpha.size == self.T:
    #        expect = np.empty((self.T, self.F))
    #        expect[idx] = (1 + U / beta[idx])**(-alpha[idx])
    #        expect[-idx] = np.exp(-U * alpha[-idx] / beta[-idx])
    #    else:
    #        raise ValueError('wrong dimension')
    #    expect[U <= -beta] = np.inf
    #    return expect


def print_gradient(name, val, grad, approx):
    print('{} = {:.2f}\tGradient: {:.2f}\tApprox: {:.2f}\t'
          '| Diff |: {:.3f}'.format(name, val, grad, approx,
                                    np.abs(grad - approx)))


def print_increment(name, last_score, score):
    diff_str = '+' if score > last_score else '-'
    print('Update ({})\tBefore: {:.2f}\tAfter: {:.2f}\t{}'.format(
        name, last_score, score, diff_str))


def comp_expect(alpha, beta):
    return (alpha / beta, special.psi(alpha) - np.log(beta))


def entropy(alpha, beta):
    ''' Compute the entropy of a r.v. theta ~ Gamma(alpha, beta)
    '''
    return (alpha - np.log(beta) + special.gammaln(alpha) +
            (1 - alpha) * special.psi(alpha))


def comp_log_exp(alpha, beta, U):
    ''' Compute log(E[exp(-au)]) where a ~ Gamma(alpha, beta) and u as a
    constant:
        log(E[exp(-au)]) = -alpha * log(1 + u / beta)
    Like self.comp_exp_expect (deprecated), this function makes extensive
    use of broadcasting. Therefore, the dimension of the input arguments
    (at least by design) can only be one of the following two situations:
        1) U: (L, F)    alpha, beta: (L, 1)
            --> output: (L, F)
        2) U: (F, )     alpha, beta: (T, 1)
            --> oupput: (T, F)
    '''
    tmp = U / beta
    log_exp = np.empty_like(tmp)
    idx = (tmp > -1)
    log_exp[idx] = (-alpha * np.log1p(tmp))[idx]
    log_exp[-idx] = np.inf
    return log_exp


def approx_grad(f, x, delta=1e-8, args=()):
    x = np.asarray(x).ravel()
    grad = np.zeros_like(x)
    diff = delta * np.eye(x.size)
    for i in xrange(x.size):
        grad[i] = (f(x + diff[i], *args) - f(x - diff[i], *args)) / (2 * delta)
    return grad
