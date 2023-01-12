
import asyncio
import websockets
import pyaudio
import threading
async def microphone_client():
    async with websockets.connect(
              'ws://127.0.0.0:5555/',ping_interval=None) as websocket:
            #   'ws://192.168.13.151:8765/',ping_interval=None) as websocket:
            #  'ws://0.0.0.0:5555/',ping_interval=None) as websocket:
        audio = pyaudio.PyAudio()
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000
        # A frame must be either 10, 20, or 30 ms in duration for webrtcvad
        FRAME_DURATION = 30
        CHUNK = int(RATE * FRAME_DURATION / 1000)
        RECORD_SECONDS = 50
        stream = audio.open(
                            format=FORMAT,
                            channels=CHANNELS,
                            rate=RATE,
                            input=True,
                            frames_per_buffer=CHUNK)
        while True:
            frame = stream.read(CHUNK, exception_on_overflow=False)
            # print(type(frame))
            await websocket.send(frame)
        
            # v=await websocket.recv()
            # print(v)


def client():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(microphone_client())
    loop.close()
if __name__ == "__main__":
    client = threading.Thread(target=client)
    client.start()
   
   