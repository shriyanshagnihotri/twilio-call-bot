from fastapi import FastAPI, Request, Response, BackgroundTasks
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Record
from pydantic import BaseModel
import os
import requests

app = FastAPI()

# Twilio credentials
account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
twilio_number = os.environ['TWILIO_PHONE_NUMBER']
machine_ip = os.environ['MAC_IP']
your_ngrok_url = f"{machine_ip}:8000"
your_ngrok_url = f"{machine_ip}"
base_path = "audio_logs"

client = Client(account_sid, auth_token)

class CallRequest(BaseModel):
    to: str

@app.post("/make_call")
async def make_call(request: CallRequest):
    call = client.calls.create(
        to=request.to,
        from_=twilio_number,
        url=f"https://{your_ngrok_url}/handle_call",
        method='POST'
    )
    return {"call_sid": call.sid}

@app.post("/handle_call")
async def handle_call(request: Request):
    response = VoiceResponse()
    response.start().stream(url=f"ws://{machine_ip}:8765")
    response.say("Welcome! Please say something after the beep.")
    response.record(
        action='/handle_recording',
        recording_status_callback='/recording_callback',
        method='POST',
        max_length=30,  # Adjust the length as needed
        transcribe=False,
        play_beep=True
    )   

    return Response(content=str(response), media_type="application/xml")

@app.post("/handle_recording")
async def handle_recording(request: Request, background_tasks: BackgroundTasks):
    # recording_url = request.query_params.get('RecordingUrl')
    # from_number = request.query_params.get('From')

    # # Download the recorded file
    # audio_file = f"{recording_url}.wav"
    # # attach user=Account SID and password=AuthToken in basic auth
    # response = requests.get(audio_file, auth=(account_sid, auth_token))
    # # response = requests.get(audio_file)
    # # create file on path with name recording_{from_number}.wav on base_path with sub folder from_number
    # if not os.path.exists(f"{base_path}/{from_number}"):
    #     os.makedirs(f"{base_path}/{from_number}")
    # with open(f"{base_path}/{from_number}/recording_{from_number}.wav", "wb") as file:
    #     file.write(response.content)

    # # Process the file in the background
    # background_tasks.add_task(process_and_respond, from_number, f"recording_{from_number}.wav")
    response = VoiceResponse()
    response.say("ok from handle recording.")
    return Response(content=str(response), media_type="application/xml")


@app.post("/recording_callback")
async def recording_callback(request: Request, background_tasks: BackgroundTasks):
    recording_status = request.query_params.get('RecordingStatus')
    recording_url = request.query_params.get('RecordingUrl')
    from_number = request.query_params.get('From')
    print(recording_status)
    pot_path = None
    if recording_status == 'completed':
        # Download the recorded file
        audio_file = f"{recording_url}"

        response = requests.get(audio_file, auth=(account_sid, auth_token))
        if not os.path.exists(f"{base_path}/{from_number}"):
            os.makedirs(f"{base_path}/{from_number}")
        pot_path = f"{base_path}/{from_number}/recording_{from_number}.wav"
        with open(pot_path, "wb") as file:
            file.write(response.content)

    # Process the file in the background
    response = VoiceResponse()
    response.say("ok from handle recording_callback.")
    process_and_respond(response, from_number, pot_path)

    return Response(content=str(response), media_type="application/xml")

def process_and_respond(response, from_number, audio_file):
    processed_file, continue_call = None, True
    if audio_file:
        processed_file, continue_call = process_file(audio_file)

    if continue_call:
        if processed_file:
            response.play(processed_file)
        # Continue the chat by asking for more input
        response.say("Please say something else after the beep.")
        response.record(
            action='/handle_recording',
            recording_status_callback='/recording_callback',
            method='POST',
            max_length=60,  # Adjust the length as needed
            transcribe=False,
            play_beep=True
        )
    else:
        if processed_file:
            response.play(processed_file)
        response.say("Thank you for your time. Goodbye!")
        response.hangup()

    # client.calls(from_number).update(twiml=str(response))

def process_file(audio_file):
    # Implement your audio processing here
    # For example, return the same file and continue_call status
    return audio_file, True  # Replace with actual logic

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
