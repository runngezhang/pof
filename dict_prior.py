'''
CREATED: 2013-05-23 10:58:16 by Dawen Liang <daliang@adobe.com>
'''

import sys

import numpy as np
import scipy.optimize as optimize
import scipy.special as special

class SF_Dict:
    def __init__(self, W, L=10, smoothness=100, seed=None, **kwargs):
        self.V = np.log(W)
        self.N, self.F = W.shape
        self.L = L
        if seed is None:
            print 'Using random seed'
            np.random.seed()
        else:
            print 'Using fixed seed {}'.format(seed)
            np.random.seed(seed) 
        self._parse_args(**kwargs)
        self._init(smoothness=smoothness)

    def _parse_args(self, **kwargs):
        pass

    def _init(self, smoothness=100):
        # model parameters
        self.U = np.random.randn(self.L, self.F)
        self.alpha = np.random.gamma(smoothness, 1./smoothness, size=(self.L,))
        self.gamma = np.random.gamma(smoothness, 1./(2*smoothness), size=(self.F,))

        # variational parameters and expectations
        self._init_variational(smoothness)

    def _init_variational(self, smoothness):
        self.mu = np.random.randn(self.N, self.L)
        self.r = np.random.gamma(smoothness, 1./smoothness, size=(self.N, self.L))
        self.EA, self.EA2, self.ElogA = self._comp_expect(self.mu, self.r)
        self.old_mu = np.inf
        self.old_r = np.inf

    def _comp_expect(self, mu, r):
        return (np.exp(mu + 1./(2*r)), np.exp(2*mu + 2./r), mu)
         
    def vb_e(self, e_converge=True, smoothness=100, maxiter=500, verbose=True):
        print 'Variational E-step...'
        if e_converge:
            # do e-step until variational inference converges
            self._init_variational(smoothness)
            for _ in xrange(maxiter):
                for l in xrange(self.L):
                    self.update_phi(l)
                    if verbose and not l % 5:
                        sys.stdout.write('.')
                if verbose:
                    sys.stdout.write('\n')
                    print 'mu increment: {:.4f}; r increment: {:.4f}'.format(np.mean(np.abs(self.old_mu - self.mu)), np.mean(np.abs(self.old_r - self.r)))
                if np.mean(np.abs(self.old_mu - self.mu)) <= 1e-3 and np.mean(np.abs(self.old_r - self.r)) <= 5 * 1e-3:
                    break
                self.old_mu = self.mu.copy()
                self.old_r = self.r.copy()
        else:
            # do e-step for one iteration
            for l in xrange(self.L):
                self.update_phi(l)
                if verbose and not l % 5:
                    sys.stdout.write('.')
            if verbose:
                sys.stdout.write('\n')

    def update_phi(self, l):                
        def _f_stub(phi, n):
            lcoef = np.exp(phi) * (np.sum(Eres[n,:] * self.U[l,:] * self.gamma) - self.alpha[l])
            qcoef = -1./2 * np.exp(2*phi) * np.sum(self.gamma * self.U[l,:]**2)
            return (lcoef, qcoef)

        def _f(phi, n):
            const = self.alpha[l] * phi
            lcoef, qcoef = _f_stub(phi, n)
            return -(const + lcoef + qcoef)
        
        def _df2(phi, n):
            const = 0
            lcoef, qcoef = _f_stub(phi, n)
            return -(const + lcoef + 4*qcoef)

        Eres = self.V - np.dot(self.EA, self.U) + np.outer(self.EA[:,l], self.U[l,:])
        for n in xrange(self.N): 
            res = optimize.minimize_scalar(_f, args=(n,))
            self.mu[n, l] = res.x
            self.r[n, l] = _df2(res.x, n)
        assert(np.all(self.r[:,l] > 0))
        self.EA[:,l], self.EA2[:,l], self.ElogA[:,l] = self._comp_expect(self.mu[:,l], self.r[:,l])

    def vb_m(self):
        print 'Variational M-step...'
        for l in xrange(self.L):
            self.update_u(l)
        self.update_gamma()
        self.update_alpha()
        self._objective()

    def update_u(self, l):
        def f(u):
            return np.sum(np.outer(self.EA2[:,l], u**2) - 2*np.outer(self.EA[:,l], u) * Eres)
        
        def df(u):
            tmp = self.EA[:,l]  # for broad-casting
            return np.sum(np.outer(self.EA2[:,l], u) - Eres * tmp[np.newaxis].T, axis=0)

        Eres = self.V - np.dot(self.EA, self.U) + np.outer(self.EA[:,l], self.U[l,:])
        u0 = self.U[l,:]
        self.U[l,:], _, d = optimize.fmin_l_bfgs_b(f, u0, fprime=df, disp=0)
        if d['warnflag']:
            if d['warnflag'] == 2:
                print 'U[{}, :]: {}, f={}'.format(l, d['task'], f(self.U[l,:]))
            else:
                print 'U[{}, :]: {}, f={}'.format(l, d['warnflag'], f(self.U[l,:]))

            app_grad = approx_grad(f, self.U[l,:])
            for idx in xrange(self.F):
                print 'U[{}, {:3d}] = {:.2f}\tApproximated: {:.2f}\tTrue: {:.2f}\t|Approximated - True|: {:.3f}'.format(l, idx,
                    self.U[l,idx], app_grad[idx], df(self.U[l,:])[idx], np.abs(app_grad[idx] - df(self.U[l,:])[idx]))


    def update_gamma(self):
        EV = np.dot(self.EA, self.U)
        EV2 = np.dot(self.EA2, self.U**2) + EV**2 - np.dot(self.EA**2, self.U**2)
        self.gamma = 1./np.mean(self.V**2 - 2 * self.V * EV + EV2, axis=0)

    def update_alpha(self):
        #def f(alpha):
        #    tmp1 = alpha * np.log(alpha) - special.gammaln(alpha)
        #    tmp2 = self.mu * (alpha - 1) - self.EA * alpha
        #    return -(self.N * tmp1.sum() + tmp2.sum())
        #def df(alpha):
        #    return -(self.N * (np.log(alpha) + 1 - special.psi(alpha)) + np.sum(self.mu - self.EA, axis=0))

        #alpha0 = self.alpha        
        #self.alpha, _, d = optimize.fmin_l_bfgs_b(f, alpha0, fprime=df, bounds=self.L * [(1e-20, None)], disp=0)
        def f(beta):
            tmp1 = np.exp(beta) * beta - special.gammaln(np.exp(beta))
            tmp2 = self.ElogA * (np.exp(beta) - 1) - self.EA * np.exp(beta)
            return -(self.N * tmp1.sum() + tmp2.sum())

        def df(beta):
            return -np.exp(beta) * (self.N * (beta + 1 - special.psi(np.exp(beta))) + np.sum(self.ElogA - self.EA, axis=0))
        
        beta0 = np.log(self.alpha)
        beta_hat, _, d = optimize.fmin_l_bfgs_b(f, beta0, fprime=df, disp=0)
        self.alpha = np.exp(beta_hat)
        if d['warnflag']:
            if d['warnflag'] == 2:
                print 'f={}, {}'.format(f(self.alpha), d['task'])
            else:
                print 'f={}, {}'.format(f(self.alpha), d['warnflag'])
            app_grad = approx_grad(f, self.alpha)
            for l in xrange(self.L):
                print 'Alpha[{:3d}] = {:.2f}\tApproximated: {:.2f}\tTrue: {:.2f}\t|Approximated - True|: {:.3f}'.format(l, self.alpha[l], app_grad[l], df(self.alpha)[l], np.abs(app_grad[l] - df(self.alpha)[l]))

    def _objective(self):
        self.obj = 1./2 * self.N * np.sum(np.log(self.gamma))
        EV = np.dot(self.EA, self.U)
        EV2 = np.dot(self.EA2, self.U**2) + EV**2 - np.dot(self.EA**2, self.U**2)
        self.obj -= 1./2 * np.sum((self.V**2 - 2 * self.V * EV + EV2) * self.gamma)
        self.obj += self.N * np.sum(self.alpha * np.log(self.alpha) - special.gammaln(self.alpha))
        self.obj += np.sum(self.ElogA * (self.alpha - 1) - self.EA * self.alpha)


def approx_grad(f, x, delta=1e-8):
    grad = np.zeros_like(x)
    diff = delta * np.eye(x.size)
    for i, _ in enumerate(x):
        grad[i] = (f(x + diff[i]) - f(x - diff[i])) / (2*delta)
    return grad
