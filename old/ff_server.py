import base64
import re
from fastapi import FastAPI, WebSocket, Request, Response
from fastapi.responses import FileResponse


import os
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from websockets.legacy.server import WebSocketServerProtocol, serve
import asyncio
import json
from datetime import datetime

app = FastAPI()
REPEAT_THRESHOLD = 50

class MediaStream:
    def __init__(self, connection: WebSocketServerProtocol):
        self.connection = connection
        self.hasSeenMedia = False
        self.messages = []
        self.repeatCount = 0

    async def processMessage(self, message: str):
        data = json.loads(message)
        if data['event'] == 'connected':
            print("From Twilio: Connected event received: ", data)
        elif data['event'] == 'start':
            print("From Twilio: Start event received: ", data)
        elif data['event'] == 'media':
            if not self.hasSeenMedia:
                # print("From Twilio: Media event received: ", data)
                print("Server: Suppressing additional messages...")
                self.hasSeenMedia = True
            self.messages.append(data)
            if len(self.messages) >= REPEAT_THRESHOLD:
                print(f"From Twilio: {len(self.messages)} omitted media messages")
                return await self.repeat()
        elif data['event'] == 'mark':
            print("From Twilio: Mark event received", data)
        elif data['event'] == 'close':
            print("From Twilio: Close event received: ", data)
            await self.close()
            return False
        return True

    async def repeat(self):
        messages = self.messages[:]
        self.messages = []
        streamSid = messages[0]['streamSid']

        messageByteBuffers = [base64.b64decode(msg['media']['payload']) for msg in messages]
        payload = base64.b64encode(b''.join(messageByteBuffers)).decode('utf-8')
        message = {
            'event': 'media',
            'streamSid': streamSid,
            'media': {
                'payload': payload,
            },
        }
        messageJSON = json.dumps(message)
        payloadRE = r'"payload":"[^"]*"'
        # print(
        #     f"To Twilio: A single media event containing the exact audio from your previous {len(messages)} inbound media messages",
        #     re.sub(payloadRE, f'"payload":"an omitted base64 encoded string with length of {len(message["media"]["payload"])} characters"', messageJSON)
        # )
        await self.connection.send_text(messageJSON)

        markMessage = {
            'event': 'mark',
            'streamSid': streamSid,
            'mark': {
                'name': f'Repeat message {self.repeatCount}',
            },
        }
        # print("To Twilio: Sending mark event", markMessage)
        await self.connection.send_text(json.dumps(markMessage))
        self.repeatCount += 1
        if self.repeatCount == 9999:
            print(f"Server: Repeated {self.repeatCount} times...closing")
            await self.connection.close(1000, 'Repeated 9999 times')
            return False
            
        return True

    async def close(self):
        print("Server: Closed")



@app.post("/twiml")
async def get():
    file_path = os.path.join(os.path.dirname(__file__), 'streams.xml')
    return FileResponse(file_path, media_type='text/xml')


@app.websocket("/streams")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ms = MediaStream(websocket)
    while True:
        data = await websocket.receive_text()
        cont = await ms.processMessage(data)
        # cont = await ms.repeat()
        if not cont:
            break
    await ms.close()