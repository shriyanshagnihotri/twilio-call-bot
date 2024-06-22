import sounddevice as sd
import soundfile as sf
import numpy as np
import wave
from scipy.io import wavfile
from scipy.signal import butter, lfilter


# Parameters for recording
sample_rate = 16000  # Sampling rate
frame_duration = 30  # Duration of a frame in milliseconds
frame_size = int(sample_rate * frame_duration / 1000)  # Number of samples per frame
silence_threshold = 150  # Adjust this threshold based on your environment
channel = 1

# Low-pass filter parameters
cutoff_frequency = 2000  # Cutoff frequency in Hz
order = 6  # Order of the filter

def play_audio(file_path):
    # Extract data and sampling rate from file
    data, fs = sf.read(file_path, dtype='int16')  
    sd.play(data, fs)
    status = sd.wait()
    
def butter_lowpass(cutoff, fs, order=5):
    nyquist = 0.5 * fs
    normal_cutoff = cutoff / nyquist
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    return b, a

def lowpass_filter(data, cutoff, fs, order=5):
    b, a = butter_lowpass(cutoff, fs, order=order)
    y = lfilter(b, a, data)
    return y

def record_until_silent(output_file, apply_filter=True) -> bool:
    silence_count = 0
    recording = True
    frames_to_write = []

    def callback(indata, frames, time, status):
        nonlocal silence_count, recording
        if status:
            print(status)

        # Ensure the input data is valid
        if indata.size == 0:
            return

        # Extract the audio channel
        audio_data = indata[:, 0]

        # Apply low-pass filter if enabled
        if apply_filter:
            audio_data = lowpass_filter(audio_data, cutoff_frequency, sample_rate, order)

        # Calculate the RMS (root mean square) of the sound
        rms = np.sqrt(np.mean(audio_data**2))

        # Handle cases where rms might be nan
        if np.isnan(rms):
            rms = 0

        # Debugging print statements
        # print(f"RMS: {rms}, Silence Count: {silence_count}, Recording: {recording}")

        # Detect if the sound level is above the threshold
        if rms > silence_threshold:
            silence_count = 0
            frames_to_write.append(audio_data.copy())
        else:
            silence_count += 1
            # Stop recording after 30 frames (1 second) of silence
            if silence_count > 30*2:
                recording = False
                raise sd.CallbackAbort

    try:
        # Start recording
        with sd.InputStream(samplerate=sample_rate, channels=channel, callback=callback, dtype='int16'):
            while recording:
                sd.sleep(100)
    except sd.CallbackAbort:
        pass

    # Write recorded frames to a file
    if frames_to_write:
        frames = np.concatenate(frames_to_write, axis=0)
        wavfile.write(output_file, sample_rate, frames.astype(np.int16))
        print(f"Recording finished. Saved to {output_file}")
        return True
    else:
        print("No audio recorded.")
        return False

    
def record_sound(file_path, duration) -> bool:
    # Extract data and sampling rate from file
    fs = 44100  # Sample rate
    print('Recording...')
    # if duration is -1, record till user stop speaking
    if duration == -1:
        return record_until_silent(file_path)
    seconds = duration  # Duration of recording
    myrecording = sd.rec(int(seconds * fs), samplerate=fs, channels=channel, dtype='int16')
    sd.wait()  # Wait until recording is finished
    sf.write(file_path, myrecording, fs)
    return True