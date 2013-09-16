# -*- coding: utf-8 -*-
# <nbformat>3.0</nbformat>

# <codecell>

import functools, glob, pickle, time

import numpy as np
import scipy.io as sio
import scipy.stats as stats
from scikits.audiolab import Sndfile, Format

import librosa
import gamma_gvpl as vpl

# <codecell>

fig = functools.partial(figure, figsize=(16,4))
specshow = functools.partial(imshow, cmap=cm.hot_r, aspect='auto', origin='lower', interpolation='nearest')

def logspec(X, amin=1e-10, dbdown=80):
    logX = 20 * np.log10(np.maximum(X, amin))
    return np.maximum(logX, logX.max() - dbdown)

def save_object(obj, filename):
    with open(filename, 'wb') as output:
        pickle.dump(obj, output, pickle.HIGHEST_PROTOCOL)
    pass

def load_object(filename):
    with open(filename, 'r') as output:
        obj = pickle.load(output)
    return obj 

# <codecell>

TIMIT_DIR = '../../timit/test/'

# <codecell>

def load_timit(wav_dir):
    f = Sndfile(wav_dir, 'r')
    wav = f.read_frames(f.nframes)
    return (wav, f.samplerate)
    
def write_wav(w, filename, channels=1, samplerate=16000):
    f_out = Sndfile(filename, 'w', format=Format(), channels=channels, samplerate=samplerate)
    f_out.write_frames(w)
    f_out.close()
    pass

# <codecell>

f_dirs_all = !ls -d "$TIMIT_DIR"dr[1-6]/f*
m_dirs_all = !ls -d "$TIMIT_DIR"dr[1-6]/m*

n_spk = 5
np.random.seed(98765)
f_dirs = np.random.permutation(f_dirs_all)[:n_spk]
m_dirs = np.random.permutation(m_dirs_all)[:n_spk]

files = [glob.glob(spk_dir + '/*.wav') for spk_dir in f_dirs]
files.extend([glob.glob(spk_dir + '/*.wav') for spk_dir in m_dirs])

# <codecell>

n_fft = 1024
hop_length = 512
lengths = []

X_complex_test = None
for file_dir in files:
    for wav_dir in file_dir[-5:]:
        wav, sr = load_timit(wav_dir)
        stft = librosa.stft(wav, n_fft=n_fft, hop_length=hop_length)
        lengths.append(stft.shape[1])
        if X_complex_test is None:
            X_complex_test = stft
        else:
            X_complex_test = np.hstack((X_complex_test, stft))

# <codecell>

# load the prior learned from training data
d = sio.loadmat('priors/sf_L50_TIMIT_spk20.mat')
U = d['U']
gamma = d['gamma'].ravel()
alpha = d['alpha'].ravel()
L = alpha.size

# <codecell>

def compute_SNR(X_complex_org, X_complex_rec, n_fft, hop_length):
    x_org = librosa.istft(X_complex_org, n_fft=n_fft, hann_w=0, hop_length=hop_length)
    x_rec = librosa.istft(X_complex_rec, n_fft=n_fft, hann_w=0, hop_length=hop_length)
    length = min(x_rec.size, x_org.size)
    snr = 10 * np.log10(np.sum( x_org[:length] ** 2) / np.sum( (x_org[:length] - x_rec[:length])**2))
    return (x_org, x_rec, snr)

# <codecell>

# only keep the contents between 400-3400 Hz
freq_high = 3400
freq_low = 400
bin_high = n_fft * freq_high / sr
bin_low = n_fft * freq_low / sr
X_cutoff_test = X_complex_test[bin_low:(bin_high+1)]

# <codecell>

F, T = X_complex_test.shape
tmpX = np.zeros((F, T))
tmpX[bin_low:(bin_high+1)] = np.abs(X_cutoff_test)

# <codecell>

encoder_test = vpl.SF_Dict(np.abs(X_cutoff_test.T), L=L, seed=98765)
encoder_test.U, encoder_test.gamma, encoder_test.alpha = U[:, bin_low:(bin_high+1)], gamma[bin_low:(bin_high+1)], alpha

encoder_test.vb_e(cold_start = False)

# <codecell>

## load the existing model if any

# <codecell>

fig(figsize=(10, 6))
specshow(encoder_test.EA.T)
colorbar()
pass

# <codecell>

# plot the correlation
A_test = encoder_test.EA.copy()
A_test = A_test - np.mean(A_test, axis=0, keepdims=True)
A_test = A_test / np.sqrt(np.sum(A_test ** 2, axis=0, keepdims=True))
specshow(np.dot(A_test.T, A_test))
colorbar()
pass

# <codecell>

EX_test = np.exp(np.dot(encoder_test.EA, U)).T

# <codecell>

EexpX = np.zeros_like(np.abs(X_complex_test))
for t in xrange(encoder_test.T):
    EexpX[:, t] = np.exp(np.sum(vpl.comp_log_exp(encoder_test.a[t, :, np.newaxis], encoder_test.b[t, :, np.newaxis], U), axis=0))

# <codecell>

freq_res = sr / n_fft

fig(figsize=(12, 3))
specshow(logspec(np.abs(X_complex_test)))
axhline(y=(bin_low+1), color='black')
axhline(y=(bin_high+1), color='black')
ylabel('Frequency (Hz)')
#yticks(arange(0, 513, 100), freq_res * arange(0, 513, 100))
xlabel('Time (sec)')
#xticks(arange(0, 2600, 500), (float(hop_length) / sr * arange(0, 2600, 500)))
colorbar()
tight_layout()
#savefig('bwe_org.eps')

fig(figsize=(12, 3))
specshow(logspec(tmpX))
ylabel('Frequency (Hz)')
#yticks(arange(0, 513, 100), freq_res * arange(0, 513, 100))
xlabel('Time (sec)')
#xticks(arange(0, 2600, 500), (float(hop_length) / sr * arange(0, 2600, 500)))
colorbar()
tight_layout()
#savefig('bwe_cutoff.eps')

fig(figsize=(12, 3))
specshow(logspec(EX_test, dbdown=115))
axhline(y=(bin_low+1), color='black')
axhline(y=(bin_high+1), color='black')
ylabel('Frequency (Hz)')
#yticks(arange(0, 513, 100), freq_res * arange(0, 513, 100))
xlabel('Time (sec)')
#xticks(arange(0, 2600, 500), (float(hop_length) / sr * arange(0, 2600, 500)))
colorbar()
tight_layout()
#savefig('bwe_rec.eps')

fig(figsize=(12, 3))
kl = sio.loadmat('kl_X_rec.mat')
EX_KL = kl['X_test_rec']
specshow(logspec(EX_KL, dbdown=90))
axhline(y=(bin_low+1), color='black')
axhline(y=(bin_high+1), color='black')
ylabel('Frequency (Hz)')
#yticks(arange(0, 513, 100), freq_res * arange(0, 513, 100))
xlabel('Time (sec)')
#xticks(arange(0, 2600, 500), (float(hop_length) / sr * arange(0, 2600, 500)))
colorbar()
tight_layout()
#savefig('bwe_kl_rec.eps')
pass

# <codecell>

_, x_test_rec_kl, snr = compute_SNR(X_complex_test, EX_KL * (X_complex_test / np.abs(X_complex_test)), n_fft, hop_length)
print 'SNR = {:.3f}'.format(snr)

# <codecell>

x_test_org, x_test_rec, snr = compute_SNR(X_complex_test, EX_test * (X_complex_test / np.abs(X_complex_test)), n_fft, hop_length)
print 'SNR = {:.3f}'.format(snr)

# <codecell>

write_wav(x_test_rec, 'bwe_demo_rec.wav')
write_wav(x_test_org, 'bwe_demo_org.wav')
write_wav(x_test_rec_kl, 'bwe_demo_rec_kl.wav')

# <codecell>

save_object(encoder_test, 'bwe_demo_encoderencoder_test')

# <codecell>


