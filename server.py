import asyncio
from importlib.resources import contents
import os
import sys
import websockets
import json
import threading
from six.moves import queue
from google.cloud import speech
from google.cloud.speech import types
import speech_recognition as sr
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor, AutoProcessor
import torch
from pydub import AudioSegment
import audioop
import numpy
import io
from textblob import TextBlob
import pymongo
import time

myclient = pymongo.MongoClient("mongodb://localhost:27017/")
mydb = myclient["stt"]

mycol = mydb["transcription"]

sys.path.append('/path/to/ffmpeg')
IP = '0.0.0.0'
PORT = 8000

class Transcoder(object):
    a=[]
    """
    Converts audio chunks to text
    """
    def __init__(self, encoding, rate, language):
        self.buff = queue.Queue()
        self.encoding = encoding
        self.language = language
        self.rate = rate
        self.closed = True
        self.energy = 300
        self.transcript = {}
        self.tokenizer=AutoProcessor.from_pretrained('jonatasgrosman/wav2vec2-large-xlsr-53-english')
        self.model=Wav2Vec2ForCTC.from_pretrained('jonatasgrosman/wav2vec2-large-xlsr-53-english')
    def start(self):
        """Start up streaming speech call"""
        threading.Thread(target=self.process).start()

    def response_loop(self, responses):
        """
        Pick up the final result of Speech to text conversion
        """
        for response in responses:
            if not response.results:
                continue
            result = response.results[0]
            if not result.alternatives:
                continue
            transcript = result.alternatives[0].transcript
            if result.is_final:
                self.transcript = transcript
    
    def translate(self,buf):
        # print("inside translate")
        adData = sr.AudioData(buf,self.rate,2)
        data=io.BytesIO(adData.get_wav_data())
        clip=AudioSegment.from_file(data)
        # print("inside translate 111")
        clip = clip.set_frame_rate(16000)# Change Channel
        clip = clip.set_channels(1)# Change Sample Width
        clip = clip.set_sample_width(2)
        x=torch.FloatTensor(clip.get_array_of_samples())
        inputs=self.tokenizer(x, sampling_rate=16000,return_tensors='pt',padding='longest').input_values
        logits=self.model(inputs).logits
        tokens=torch.argmax(logits, axis=-1)
        text=self.tokenizer.batch_decode(logits.detach().numpy()).text
        print(text)
        self.transcript.update({"text":text})
        return text
        

    def process(self):
        """
        Audio stream recognition and result parsing
        """
        #You can add speech contexts for better recognition
        audio_generator = self.stream_generator()
        # print("Inside process")
        
        for content in audio_generator:
            # print("Inside loop")
            self.translate(content)

        try:
            # pass
            self.response_loop(responses=responses)
        except:
            self.start()

    def stream_generator(self):
        while not self.closed:
            chunk = self.buff.get()
            self.a.append(chunk)            
            if chunk is None:
                return
            data = [chunk]            
            

            while True:
            # for i in range (len(chunk)):

                try:
                    chunk = self.buff.get(block=False)
                    # if chunk is "":
                    #     return
                    energy = audioop.rms(chunk, 2)
                    # print(energy)
                    if energy > 3000:
                        # print(energy)
                        data.append(chunk)
                except queue.Empty:
                    break
            yield b''.join(data)

    def write(self, data):
        """
        Writes data to the buffer
        """
        self.buff.put(data)


async def audio_processor(websocket, path):
    """
    Collects audio from the stream, writes it to buffer and return the output of Google speech to text
    """
    config = await websocket.recv()
    if not isinstance(config, str):
        print("ERROR, no config")
        return
    config = json.loads(config)
    print(config)
    transcoder = Transcoder(
        encoding=config["format"],  
        rate=config["rate"],
        language=config["language"]
    )
    transcoder.start()
    while True:
        try:
            data = await websocket.recv()
            # print(data)
                        
        except websockets.ConnectionClosed:
            print("Connection closed")
            break
        transcoder.write(data)
        transcoder.closed = False                 
        a=transcoder.transcript
        c=json.dumps(a)
        await asyncio.sleep(1)              
        await websocket.send(c)            
        transcoder.transcript = {}  
                       
            
            
####################### recevie the packets ##############################
start_server = websockets.serve(audio_processor, IP, PORT)
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()

####################################################################################
################## re send the  packets ############################################
# asyncio.get_event_loop().run_until_complete(microphone_client())