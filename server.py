import base64
import logging
import json
import os
import numpy as np
import soundfile as sf
import audioop
from fastapi import FastAPI, WebSocket, Request, Response, BackgroundTasks, WebSocketDisconnect
from websockets.legacy.server import WebSocketServerProtocol, serve
from scipy.signal import find_peaks
from queue import Queue, Empty
import vosk
import bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from fastapi.concurrency import run_in_threadpool

app = FastAPI()
model = vosk.Model('vosk-model-en-in-0.5')
agent = bot.deploy()


REMOTE_DOMAIN = os.getenv("REMOTE_DOMAIN", "localhost:8000")

REPEAT_THRESHOLD = 100
SILENCE_THRESHOLD = 1000  # Adjust this threshold based on your needs

CL = '\x1b[0K'
BS = '\x08'

def convert_and_encode_wav(file_path):
    with open(file_path, "rb") as wav_file:
        # Read the file as bytes
        wav_bytes = wav_file.read()
        # Encode the bytes to base64
        encoded_bytes = base64.b64encode(wav_bytes)
        # Convert the base64 bytes to a string
        encoded_str = encoded_bytes.decode('utf-8')
    return encoded_str


FIRST_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
<Say>{hi_message}</Say>
<pause length="10"/>
<Connect>
<Stream url="wss://{server_domain}/streams">
<Parameter name="aCutomParameter" value="aCustomValue that was set in TwiML" />
</Stream>
</Connect>
<Say>{bye_message}</Say>
</Response>"""

def start_agent():
    global agent, logger
    logger.info("Agent started")    
    agent.initiate_chat()
    agent.close()


class MediaStream:
    def __init__(self, connection: WebSocketServerProtocol):
        self.connection = connection
        self.hasSeenMedia = False
        self.messages = []
        self.repeatCount = 0
        self.audio_buffer = np.array([], dtype=np.int16)
        self.file_counter = 0
        self.rec = vosk.KaldiRecognizer(model, 16000)
        self.out_messages = []
        self.in_messages = []
        
    async def load_out_message(self):
        if agent.how_to_speak:
            self.out_messages = agent.how_to_speak
            agent.how_to_speak = []
        
    async def create_in_message(self, message):
        self.in_messages.append(message)
        await self.set_in_messages()

    async def set_in_messages(self):
        agent.how_to_listen = "".join(self.in_messages)
        self.in_messages = []
        
    
    async def processMessage(self, message: str):
        rec = self.rec
        data = json.loads(message)
        if data['event'] == 'connected':
            logger.info("From Twilio: Connected event received: ", data)
        elif data['event'] == 'start':
            logger.info("From Twilio: Start event received: ", data)
        elif data['event'] == 'media':
            if not self.hasSeenMedia:
                # logger.info("From Twilio: Media event received: ", data)
                logger.info("Server: Suppressing additional messages...")
                self.hasSeenMedia = True

            audio = base64.b64decode(data['media']['payload'])
            audio = audioop.ulaw2lin(audio, 2)
            audio = audioop.ratecv(audio, 2, 1, 8000, 16000, None)[0]
            self.messages.append(data)
            # logger.info(audio)
            
            if rec.AcceptWaveform(audio):
                r = json.loads(rec.Result())
                # logger.info(CL + r['text'] + ' ', end='', flush=True)
                logger.info(r['text'])
                await self.create_in_message(r['text'])
            else:
                pass
                # r = json.loads(rec.PartialResult())
                # logger.info(CL + r['partial'] + BS * len(r['partial']), end='', flush=True)
            
            # if len(self.messages) >= REPEAT_THRESHOLD:
            await self.load_out_message()
            if len(self.out_messages) > 0:
                return await self.repeat()
            # 
            #     # self._process_audio_buffer()
            #     # logger.info(f"From Twilio: {len(self.messages)} omitted media messages")
                
        elif data['event'] == 'mark':
            logger.info("From Twilio: Mark event received", data)
            pass
        elif data['event'] == 'close':
            logger.info("From Twilio: Close event received: ", data)
            await self.close()
            return False
        return True

    # def _process_audio_buffer(self):
    #     if len(self.audio_buffer) == 0:
    #         return

    #     # Detect silence based on the amplitude of the audio signal
    #     peaks, _ = find_peaks(self.audio_buffer, height=SILENCE_THRESHOLD)
    #     if len(peaks) > 0:
    #         end = peaks[-1] + 1
    #         nonsilent_audio = self.audio_buffer[:end]
    #         file_path = f"temp/audio_chunk_{self.file_counter}.wav"
    #         sf.write(file_path, nonsilent_audio, 44100) #, subtype='PCM_16')
    #         self.file_counter += 1

    #         # Remove the processed part from the buffer
    #         self.audio_buffer = self.audio_buffer[end:]

    async def repeat(self):
        messages = self.messages[:]
        self.messages = []
        streamSid = messages[0]['streamSid']

        
        # messageByteBuffers = [base64.b64decode(msg['media']['payload']) for msg in messages]

        # payload = base64.b64encode(b''.join(messageByteBuffers)).decode('utf-8')
        
        # logger.info(f"Server: Sending audio payload {payload}")

        messageByteBuffers = []
        for file_path in self.out_messages:
            logger.info(f"Server: trying to Send audio {file_path}")
            # load wav file
            # data, _ = sf.read(file_path, dtype='float32')
            # payload = base64.b64encode(data.tobytes()).decode('utf-8')
            # payload = data.tobytes().decode('utf-8')
            payload = convert_and_encode_wav(file_path)
            message = {
                'event': 'media',
                'streamSid': streamSid,
                'media': {
                    'payload': payload,
                },
            }
            messageJSON = json.dumps(message)
            
            await self.connection.send_text(messageJSON)
        
            
            markMessage = {
                'event': 'mark',
                'streamSid': streamSid,
                'mark': {
                    'name': f'Repeat message {self.repeatCount}',
                },
            }
            await self.connection.send_text(json.dumps(markMessage))
        self.out_messages = []
            
        self.repeatCount += 1
        if self.repeatCount == 9999:
            logger.info(f"Server: Repeated {self.repeatCount} times...closing")
            await self.connection.close(1000, 'Repeated 9999 times')
            return False
            
        return True

    async def close(self):
        try:
            await self.connection.close(1000, 'closing...')
        except Exception as e:
            logger.info(f"Server: Error closing connection: {e}")
        logger.info("Server: Closed")


@app.post("/twiml")
async def get(background_tasks: BackgroundTasks):
    background_tasks.add_task(start_agent)
    # prepare XML response
    return Response(content=FIRST_RESPONSE.format(hi_message="Hello", bye_message="Goodbye", server_domain=REMOTE_DOMAIN), media_type="application/xml")

@app.websocket("/streams")
async def websocket_endpoint(websocket: WebSocket, background_tasks: BackgroundTasks):
    await websocket.accept()
    MS = MediaStream(websocket)    
    try:
        while True:
            data = await websocket.receive_text()
            cont = await MS.processMessage(data)
            if not cont:
                break
    except WebSocketDisconnect:
        await MS.close()


