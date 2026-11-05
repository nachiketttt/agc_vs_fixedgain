"""
AGC vs Fixed Gain  ADC Quantization Simulation
"""

import numpy as np
import matplotlib.pyplot as plt


# ---------- 1. Signal generation ----------
def generate_signals(fs, duration, f_wanted, f_interferer, amp_wanted, amp_interferer):
    """
    fs            = sample rate (Hz)
    duration      = length of the capture (seconds)
    f_wanted      = frequency of the wanted (weak) signal (Hz)
    f_interferer  = frequency of the interferer (strong) signal (Hz)
    amp_wanted    = amplitude of the wanted signal (small, e.g. 0.001)
    amp_interferer= amplitude of the interferer (large, e.g. 0.9)

    Returns: t, wanted, interferer, combined
    """
    t = np.arange(0, duration, 1/fs)
    wanted = amp_wanted * np.sin(2*np.pi*f_wanted*t)
    interferer = amp_interferer * np.sin(2*np.pi*f_interferer*t)
    
    gate = np.ones_like(t)          # all ones = interferer on
    gate[len(t)//2:] = 0            # second half = interferer off
    interferer = interferer * gate
    
    combined = wanted + interferer  
    return t, wanted, interferer, combined, gate


# ---------- 2. ADC quantizer ----------
def quantize(signal, bits, full_scale):
    """
    Simulate a fixed-bit-depth ADC.
    - Clip anything outside +/- full_scale (this IS the clipping behavior)
    - Round whatever remains to the nearest of 2**bits discrete levels
      spread across the +/- full_scale range

    Returns the quantized signal (same shape as input).
    """
    clipped = np.clip(signal, -full_scale, full_scale)
    levels = 2 ** bits
    step = (2 * full_scale) / levels
    quantized = np.round(clipped / step) * step
    return quantized, clipped, levels, step


# ---------- 3. Fixed gain scenario ----------
def apply_fixed_gain(combined, interferer_amp, full_scale, margin=0.95):
    """
    Pick ONE gain value, sized so the interferer's peak fits just inside
    full_scale (with a small safety margin so it doesn't clip exactly
    at the edge), and apply it to the whole signal.

    Returns: (gained_signal, gain_used)
    """
    peak = np.max(np.abs(combined))
    gain = (full_scale * margin) / np.max(np.abs(combined))
    return combined * gain, gain, peak


# ---------- 4. Block-wise AGC ----------
def apply_agc(combined, block_size, target_power):
    """
    Split combined into chunks of block_size samples. For each block:
      - compute its average power  (mean of signal squared)
      - compute the gain that would bring that block's average power
        up/down to target_power
      - apply that gain to just this block

    Returns: (rescaled_signal, gains_per_block)
    Tip: print gains_per_block while testing you can see it jump
    when the interferer switches on vs off in your test signal.
    """
    n_blocks = len(combined) // block_size
    rescaled = np.zeros_like(combined)
    gains_per_block = []

    for i in range(n_blocks):
        start = i * block_size
        end = start + block_size
        block = combined[start:end]

        block_power = np.mean(block ** 2)
        gain = np.sqrt(target_power / block_power)

        rescaled[start:end] = block * gain
        gains_per_block.append(gain)

    return rescaled, gains_per_block


# ---------- 5. SNR calculation ----------
def compute_snr(signal_component, noise_component):
    """
    signal_component = the wanted signal's power contribution
    noise_component   = everything else (quantization error, etc.)

    SNR_dB = 10 * log10(signal_power / noise_power)

    Hint for getting signal_component and noise_component:
    quantize a PURE wanted-signal-only waveform (no interferer) through
    the same gain/quantize pipeline, and separately get the quantization
    ERROR by subtracting the quantized output from the un-quantized
    (pre-ADC) signal. That error IS your noise.
    """
    signal_power = np.mean(signal_component ** 2)
    noise_power = np.mean(noise_component ** 2)
    snr_db = 10 * np.log10(signal_power / noise_power)
    return snr_db
    
# ---------- 6. SNR calculation per block ----------
def block_snrs(wanted_after_gain, noise, block_size):
    out = []
    for i in range(len(noise) // block_size):
        start = i * block_size
        end = start + block_size
        out.append(compute_snr(wanted_after_gain[start:end], noise[start:end]))
    return out


# ---------- 6. Run both scenarios and plot ----------
if __name__ == "__main__":
    # --- parameters, tweak freely ---
    fs = 1_000_000          # 1 MHz sample rate
    duration = 0.01          # 10 ms capture
    f_wanted = 50_000        # 50 kHz
    f_interferer = 200_000   # 200 kHz
    amp_wanted = 0.001       # weak
    amp_interferer = 0.9     # strong
    full_scale = 1.0
    block_size = 1000        # samples per AGC block
    target_power = 10 ** (-12 / 10)  # -12 dBFS, matches real Pluto AGC target

    # Run fixed gain + quantize for 8-bit and 12-bit
    # STEP 1: generating dummy signals
    t, wanted, interferer, combined, gate = generate_signals(fs, duration, f_wanted, f_interferer, amp_wanted, amp_interferer)

    # STEP 2: Applying fixed gain
    margin=0.95
    after_gain_combined, gain, peak = apply_fixed_gain(combined, amp_interferer, full_scale, margin) 
    print("Fixed gain per block:", np.round(gain,1))
    
    # STEP 3: Quantizing both signals combined after passing through fixed gain
    bits8=8
    quantized_8bits, clipped, levels, step = quantize(after_gain_combined, bits8, full_scale)
    
    bits12=12
    quantized_12bits, clipped, levels, step = quantize(after_gain_combined, bits12, full_scale)
    
    
    # Run AGC + quantize for 8-bit and 12-bit
    # STEP 1: Applying AGC to combined
    rescaled, gains_per_block = apply_agc(combined, block_size, target_power)
    print("Gains induced by AGC per block:", np.round(gains_per_block, 1))
    # STEP 2: Quantizing both signals combined after passing through AGC
    bits8=8
    quantized_8bits_agc, clipped, levels, step = quantize(rescaled, bits8, full_scale)
    
    bits12=12
    quantized_12bits_agc, clipped, levels, step = quantize(rescaled, bits12, full_scale)
    
    
    # Compute SNR for each case
    # SNR for fixed gain 8 bit quant and 12 bit quant
    snr8_fixed = block_snrs(wanted * gain, quantized_8bits - after_gain_combined, block_size) 
    snr12_fixed = block_snrs(wanted * gain, quantized_12bits - after_gain_combined, block_size) 
    
    # Block wise SNR for AGC 8 and 12 bit quant
    gain_per_sample = np.repeat(gains_per_block, block_size)
    snr8_agc = block_snrs(wanted * gain_per_sample, quantized_8bits_agc - rescaled, block_size)
    snr12_agc = block_snrs(wanted * gain_per_sample, quantized_12bits_agc - rescaled, block_size)
    
    print("SNR for fixed 8 :", np.round(snr8_fixed, 1))
    print("SNR for fixed 12:", np.round(snr12_fixed, 1))
    print("SNR for agc 8   :", np.round(snr8_agc, 1))
    print("SNR for agc 12  :", np.round(snr12_agc, 1))
    
    
    # Final bar or line plot comparing SNR across: fixed-8bit, fixed-12bit,
    #       agc-8bit, agc-12bit
    blocks = np.arange(len(snr8_fixed))   # [0, 1, 2, ... 9], the x-axis

    plt.figure()                           # open one new empty window

    plt.plot(blocks, snr8_fixed,  'o-',  label="Fixed gain, 8-bit")
    plt.plot(blocks, snr12_fixed, 'o-', label="Fixed gain, 12-bit")
    plt.plot(blocks, snr8_agc,    's--',  label="AGC, 8-bit")
    plt.plot(blocks, snr12_agc,   's--', label="AGC, 12-bit")

    plt.axvline(4.5, color='gray', linestyle=':')   # vertical line where the interferer switches off

    plt.xlabel("Block number")
    plt.ylabel("Wanted-signal SNR (dB)")
    plt.title("Wanted signal SNR: fixed gain vs AGC")
    plt.legend()                           # draws the key using the label= names
    plt.grid(True)
    plt.show()                             # actually displays the window
