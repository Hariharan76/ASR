
import asyncio
import time
import websockets
import json
import threading
from six.moves import queue
#from google.cloud import speech
#from google.cloud.speech import types
from halo import Halo
import whisper
import torch
from better_profanity import profanity
import numpy as np
import webrtcvad
import collections
import torchaudio
import multiprocessing as mp
vad = webrtcvad.Vad(3)
vad.set_mode(3)

import argparse
parser = argparse.ArgumentParser(
    description="Stream from microphone to webRTC and silero VAD")

parser.add_argument('-v', '--webRTC_aggressiveness', type=int, default=5,
                    help="Set aggressiveness of webRTC: an integer between 0 and 3, 0 being the least aggressive about filtering out non-speech, 3 the most aggressive. Default: 3")
parser.add_argument('--nospinner', action='store_true',
                    help="Disable spinner")
parser.add_argument('-d', '--device', type=int, default=None,
                    help="Device input index (Int) as listed by pyaudio.PyAudio.get_device_info_by_index(). If not provided, falls back to PyAudio.get_default_device().")

parser.add_argument('-name', '--silaro_model_name', type=str, default="silero_vad",
                    help="select the name of the model. You can select between 'silero_vad',''silero_vad_micro','silero_vad_micro_8k','silero_vad_mini','silero_vad_mini_8k'")
parser.add_argument('--reload', action='store_true',
                    help="download the last version of the silero vad")

parser.add_argument('-ts', '--trig_sum', type=float, default=0.25,
                    help="overlapping windows are used for each audio chunk, trig sum defines average probability among those windows for switching into triggered state (speech state)")

parser.add_argument('-nts', '--neg_trig_sum', type=float, default=0.07,
                    help="same as trig_sum, but for switching from triggered to non-triggered state (non-speech)")

parser.add_argument('-N', '--num_steps', type=int, default=8,
                    help="nubmer of overlapping windows to split audio chunk into (we recommend 4 or 8)")

parser.add_argument('-nspw', '--num_samples_per_window', type=int, default=4000,
                    help="number of samples in each window, our models were trained using 4000 samples (250 ms) per window, so this is preferable value (lesser values reduce quality)")

parser.add_argument('-msps', '--min_speech_samples', type=int, default=10000,
                    help="minimum speech chunk duration in samples")

parser.add_argument('-msis', '--min_silence_samples', type=int, default=0,
                    help=" minimum silence duration in samples between to separate speech chunks")
ARGS = parser.parse_args()
ARGS.rate = 16000
class Transcoder(object):
    """
    Converts audio chunks to text
    """
    global file
    def __init__(self):
        self.buff = queue.Queue()
        self.closed = True
        self.transcript = None
        self.input_rate = 16000

        self.file = whisper.load_model("small")
        self.transcript = {}

    def start1(self):
        """Start up streaming speech call"""
        threading.Thread(target=lambda: self.process()).start()
        # commander = multiprocessing.Process(target=run_commander)
        # commander.start()

    def process(self):
        print("Listening (ctrl-C to exit)...")
        frames = self.stream_generator()
        torchaudio.set_audio_backend("soundfile")
        model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                    model=ARGS.silaro_model_name,
                                    force_reload=ARGS.reload,
                                    onnx=True)
        (get_speech_timestamps,save_audio,read_audio,VADIterator,collect_chunks) = utils

        # Stream from microphone to Wav2Vec 2.0 using VAD
        print("audio length\tinference time\ttext")
        spinner = None
        if not ARGS.nospinner:
            spinner = Halo(spinner='line')
        wav_data = bytearray()
        try:
            for frame in frames:
                if frame is not None:
                    if spinner:
                        spinner.start()

                    wav_data.extend(frame)
                else:
                    if spinner:
                        spinner.stop()
                    #print("webRTC has detected a possible speech")

                    newsound = np.frombuffer(wav_data, np.int16)
                    audio_float32 = torch.from_numpy(np.frombuffer(newsound, dtype=np.int16).astype('float32') / 32767)
                    time_stamps = get_speech_timestamps(audio_float32, model, sampling_rate=ARGS.rate)

                    if(len(time_stamps) > 0):
                        #print("silero VAD has detected a possible speech")

                        text = self.file.transcribe(audio_float32.numpy(),fp16=False, language='English')
                        final_result=text["text"]
                        self.transcript.update({"text":final_result})
                    else:
                        print("VAD detected noise")
                    wav_data = bytearray()
        except KeyboardInterrupt:
            exit()
    def stream_generator(self):
        FRAME_DURATION = 30
        padding_ms=300
        ratio=0.75
        sample_rate =16000
        frames=None
        if frames is None:
            frames = self.frame_generator()
        num_padding_frames = padding_ms // FRAME_DURATION
        ring_buffer = collections.deque(maxlen=num_padding_frames)
        triggered = False

        for frame in frames:
            if len(frame) < 640:
                return

            is_speech = vad.is_speech(frame, sample_rate)

            if not triggered:
                ring_buffer.append((frame, is_speech))
                num_voiced = len([f for f, speech in ring_buffer if speech])
                if num_voiced > ratio * ring_buffer.maxlen:
                    triggered = True
                    for f, s in ring_buffer:
                        yield f
                    ring_buffer.clear()

            else:
                yield frame
                ring_buffer.append((frame, is_speech))
                num_unvoiced = len(
                    [f for f, speech in ring_buffer if not speech])
                if num_unvoiced > ratio * ring_buffer.maxlen:
                    triggered = False
                    yield None
                    ring_buffer.clear()

    def frame_generator(self):
        """Generator that yields all audio frames from microphone."""
        if self.input_rate == 16000:
            while True:
                yield self.write()
        else:
            raise Exception("Resampling required")


    def write(self):

        return self.buff.get()


IP ="127.0.0.0"
PORT =5555
async def audio_processor(websocket, path):
    """
    Collects audio from the stream, writes it to buffer and return the output of Google speech to text
    """
    transcoder = Transcoder()
    transcoder.start1()

    try:
        # while True:
                # msg = await websocket.recv()
            async for message in websocket:
                transcoder.buff.put( (message) )
                transcoder.closed = False
                if transcoder.transcript:
                    print(transcoder.transcript)
                    b=json.dumps(transcoder.transcript)
                    transcoder.transcript = {}
                    await websocket.send(b)
    except websockets.ConnectionClosed:
        print("Connection closed")

def run_logger():
    start_logger = websockets.serve(audio_processor, IP, PORT)
    print("server start")
    asyncio.get_event_loop().run_until_complete(start_logger)
    asyncio.get_event_loop().run_forever()
    mp.set_start_method('spawn')

if __name__ == '__main__':
    # file = whisper.load_model("large.pt")
    q = mp.Queue()
    p = mp.Process(target=run_logger)
    p.start()
    p.join()