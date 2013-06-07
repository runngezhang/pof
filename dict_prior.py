"""
CREATED: 2013-05-23 10:58:16 by Dawen Liang <daliang@adobe.com>
"""

import logging, time

import numpy as np
import scipy.optimize as optimize
import scipy.special as special

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(asctime)s %(filename)s:%(lineno)d  %(message)s')
logger = logging.getLogger('dict_prior')

class SF_Dict:
    def __init__(self, W, L=10, smoothness=100, seed=None):
        self.V = np.log(W)
        self.T, self.F = W.shape
        self.L = L
        if seed is None:
            logger.info('Using random seed')
            np.random.seed()
        else:
            logger.info('Using fixed seed {}'.format(seed))
            np.random.seed(seed) 
        self._init(smoothness=smoothness)

    def _init(self, smoothness=100):
        # model parameters
        self.U = np.random.randn(self.L, self.F)
        self.alpha = np.random.gamma(smoothness, 1./smoothness, size=(self.L,))
        self.gamma = np.random.gamma(smoothness, 1./(2*smoothness), size=(self.F,))

        self.old_U_inc = np.inf
        self.old_alpha_inc = np.inf
        self.old_gamma_inc = np.inf

        # variational parameters and expectations
        self._init_variational(smoothness)

    def _init_variational(self, smoothness):
        self.mu = np.random.randn(self.T, self.L)
        self.r = np.random.gamma(smoothness, 1./smoothness, size=(self.T, self.L))
        self.EA, self.EA2, self.ElogA = self._comp_expect(self.mu, self.r)

        self.old_mu_inc = np.inf 
        self.old_r_inc = np.inf

    def _comp_expect(self, mu, r):
        return (np.exp(mu + 1./(2*r)), np.exp(2*mu + 2./r), mu)
         
    def vb_e(self, cold_start=True, smoothness=100, conv_check=1, maxiter=500, atol=1e-3):
        """ Perform one variational E-step, which may have one sub-iteration or
        multiple sub-iterations if e_converge is set to True, to appxorimate the 
        posterior P(A | -)

        Parameters
        ----------
        cold_start: bool
            Do e-step with fresh initialization until convergence if true, otherwise just to one sub-iteration.
        smoothness: float
            Smootheness of the variational initialization, larger value will
            lead to more concentrated initialization.
        conv_check: int
            Check convergence on the first-order difference if 1 or second-order
            difference if 2. 
        maxiter: int
            Maximal number of iterations in one e-step.
        atol: float 
            Absolute convergence threshold. 

        """
        logger.info('Variational E-step...')
        if cold_start:
            # do e-step until variational inference converges
            self._init_variational(smoothness)
            for i in xrange(maxiter):
                old_mu = self.mu.copy()
                old_r = self.r.copy()
                start_t = time.time()
                for l in xrange(self.L):
                    self.update_phi(l)
                t = time.time() - start_t
                mu_diff = np.mean(np.abs(old_mu - self.mu))
                sigma_diff = np.mean(np.abs(np.sqrt(1./old_r) - np.sqrt(1./self.r)))
                logger.info('Subiter: {:3d}\tmu increment: {:.4f}\tsigma increment: {:.4f}\ttime: {:.2f}'.format(i, mu_diff, sigma_diff, t))
                if conv_check == 1:
                    if mu_diff <= atol and sigma_diff <= atol:
                        break
                elif conv_check == 2:
                    if self.old_mu_inc - mu_diff <= atol and self.old_r_inc - sigma_diff <= atol:
                        break
                    self.old_mu_inc = mu_diff
                    self.old_r_inc = sigma_diff
                else:
                    raise ValueError('conv_check can only be 1 or 2')
        else:
            # do e-step for one iteration
            for l in xrange(self.L):
                self.update_phi(l)

    def update_phi(self, l):                
        def _f_stub(phi, t):
            lcoef = np.exp(phi) * (np.sum(Eres[t,:] * self.U[l,:] * self.gamma) - self.alpha[l])
            qcoef = -1./2 * np.exp(2*phi) * np.sum(self.gamma * self.U[l,:]**2)
            return (lcoef, qcoef)

        def _f(phi, t):
            const = self.alpha[l] * phi
            lcoef, qcoef = _f_stub(phi, t)
            return -(const + lcoef + qcoef)
                
        def _df(phi, t):
            const = self.alpha[l]
            lcoef, qcoef = _f_stub(phi, t)
            return -(const + lcoef + 2*qcoef)

        def _df2(phi, t):
            lcoef, qcoef = _f_stub(phi, t)
            return -(lcoef + 4*qcoef)

        Eres = self.V - np.dot(self.EA, self.U) + np.outer(self.EA[:,l], self.U[l,:])
        for t in xrange(self.T): 
            self.mu[t, l], _, d = optimize.fmin_l_bfgs_b(_f, self.mu[t, l], fprime=_df, args=(t,), disp=0)
            tmp_r = _df2(self.mu[t, l], t)
            if tmp_r <= 0:
                if d['warnflag'] == 2:
                    logger.debug('Phi[{}, {}]: {}, f={}'.format(t, l, d['task'], _f(self.mu[t, l], t)))
                else:
                    logger.debug('Phi[{}, {}]: {}, f={}'.format(t, l, d['warnflag'], _f(self.mu[t, l], t)))
                app_grad = approx_grad(_f, self.mu[t, l], args=(t,))[0]
                app_hessian = approx_grad(_df, self.mu[t, l], args=(t,))[0]
                logger.debug('Approximated: {:.5f}\tGradient: {:.5f}\t|Approximated - True|: {:.5f}'.format(app_grad, _df(self.mu[t, l], t), np.abs(app_grad - _df(self.mu[t, l], t))))
                logger.debug('Approximated: {:.5f}\tHessian: {:.5f}\t|Approximated - True|: {:.5f}'.format(app_hessian, tmp_r, np.abs(app_hessian - _df2(self.mu[t, l], t))))
                # Try Brent
                res = optimize.minimize_scalar(_f, args=(t,))
                self.mu[t, l] = res.x
                tmp_r = _df2(res.x, t)
                logger.warning('LBFGS failed, try Brent ==>\tGradient: {:.5f}\tHessian: {:5f}'.format(_df(self.mu[t, l], t), tmp_r))
            self.r[t, l] = tmp_r 

        assert(np.all(self.r[:,l] > 0))
        self.EA[:,l], self.EA2[:,l], self.ElogA[:,l] = self._comp_expect(self.mu[:,l], self.r[:,l])

    def vb_m(self, conv_check=1, atol=0.01):
        """ Perform one M-step, update the model parameters with A fixed from E-step

        Parameters
        ----------
        conv_check: int
            Check convergence on the first-order difference if 1 or second-order
            difference if 2. 
        atol: float
            Absolute convergence threshold.

        """

        logger.info('Variational M-step...')
        old_U = self.U.copy()
        old_gamma = self.gamma.copy()
        old_alpha = self.alpha.copy()
        for l in xrange(self.L):
            self.update_u(l)
        self.update_gamma()
        self.update_alpha()
        self._objective()
        U_diff = np.mean(np.abs(self.U - old_U))
        sigma_diff = np.mean(np.abs(np.sqrt(1./self.gamma) - np.sqrt(1./old_gamma)))
        alpha_diff = np.mean(np.abs(self.alpha - old_alpha))
        logger.info('U increment: {:.4f}\tsigma increment: {:.4f}\talpha increment: {:.4f}'.format(U_diff, sigma_diff, alpha_diff))
        if conv_check == 1:
            if U_diff < atol and sigma_diff < atol and alpha_diff < atol:
                return True
        elif conv_check == 2:
            if self.old_U_inc - U_diff < atol and self.old_gamma_inc - sigma_diff < atol and self.old_alpha_inc - alpha_diff < atol:
                return True
            self.old_U_inc = U_diff
            self.old_gamma_inc = sigma_diff
            self.old_alpha_inc = alpha_diff
        else:
            raise ValueError('conv_check can only be 1 or 2')
        return False

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
                logger.debug('U[{}, :]: {}, f={}'.format(l, d['task'], f(self.U[l,:])))
            else:
                logger.debug('U[{}, :]: {}, f={}'.format(l, d['warnflag'], f(self.U[l,:])))

            app_grad = approx_grad(f, self.U[l,:])
            for idx in xrange(self.F):
                logger.debug('U[{}, {:3d}] = {:.2f}\tApproximated: {:.2f}\tGradient: {:.2f}\t|Approximated - True|: {:.3f}'.format(l, idx, self.U[l,idx], app_grad[idx], df(self.U[l,:])[idx], np.abs(app_grad[idx] - df(self.U[l,:])[idx])))


    def update_gamma(self):
        EV = np.dot(self.EA, self.U)
        EV2 = np.dot(self.EA2, self.U**2) + EV**2 - np.dot(self.EA**2, self.U**2)
        self.gamma = 1./np.mean(self.V**2 - 2 * self.V * EV + EV2, axis=0)

    def update_alpha(self):
        def f(eta):
            tmp1 = np.exp(eta) * eta - special.gammaln(np.exp(eta))
            tmp2 = self.ElogA * (np.exp(eta) - 1) - self.EA * np.exp(eta)
            return -(self.T * tmp1.sum() + tmp2.sum())

        def df(eta):
            return -np.exp(eta) * (self.T * (eta + 1 - special.psi(np.exp(eta))) + np.sum(self.ElogA - self.EA, axis=0))
        
        eta0 = np.log(self.alpha)
        eta_hat, _, d = optimize.fmin_l_bfgs_b(f, eta0, fprime=df, disp=0)
        self.alpha = np.exp(eta_hat)
        if d['warnflag']:
            if d['warnflag'] == 2:
                logger.debug('f={}, {}'.format(f(self.alpha), d['task']))
            else:
                logger.debug('f={}, {}'.format(f(self.alpha), d['warnflag']))
            app_grad = approx_grad(f, self.alpha)
            for l in xrange(self.L):
                logger.debug('Alpha[{:3d}] = {:.2f}\tApproximated: {:.2f}\tGradient: {:.2f}\t|Approximated - True|: {:.3f}'.format(l, self.alpha[l], app_grad[l], df(self.alpha)[l], np.abs(app_grad[l] - df(self.alpha)[l])))

    def _objective(self):
        self.obj = 1./2 * self.T * np.sum(np.log(self.gamma))
        EV = np.dot(self.EA, self.U)
        EV2 = np.dot(self.EA2, self.U**2) + EV**2 - np.dot(self.EA**2, self.U**2)
        self.obj -= 1./2 * np.sum((self.V**2 - 2 * self.V * EV + EV2) * self.gamma)
        self.obj += self.T * np.sum(self.alpha * np.log(self.alpha) - special.gammaln(self.alpha))
        self.obj += np.sum(self.ElogA * (self.alpha - 1) - self.EA * self.alpha)


def approx_grad(f, x, delta=1e-8, args=()):
    x = np.asarray(x).ravel()
    grad = np.zeros_like(x)
    diff = delta * np.eye(x.size)
    for i in xrange(x.size):
        grad[i] = (f(x + diff[i], *args) - f(x - diff[i], *args)) / (2*delta)
    return grad
