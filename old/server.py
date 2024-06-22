from fastapi import FastAPI, Request, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from pydantic import BaseModel
import os

app = FastAPI()

# Twilio credentials
account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
twilio_number = os.environ['TWILIO_PHONE_NUMBER']
machine_ip = os.environ['MAC_IP']
your_ngrok_url = f"{machine_ip}:8000"

client = Client(account_sid, auth_token)

class CallRequest(BaseModel):
    to: str
    

questions_and_responses = [
    {"question": "What is your name?", "response": "Thank you for your response."},
    {"question": "How can we help you today?", "response": "We appreciate your feedback."},
    # Add more questions and responses as needed
]

current_question_index = {}

@app.post("/make_call")
async def make_call(request: CallRequest):
    call = client.calls.create(
        to=request.to,
        from_=twilio_number,
        url=f"http://{machine_ip}:8000/handle_call"
    )
    return {"call_sid": call.sid}

@app.post("/handle_call")
async def handle_call(request: Request):    
    from_number = request.query_params.get('From')
    current_question_index[from_number] = 0

    response = VoiceResponse()
    response.start().stream(url=f"ws://{machine_ip}:8765")
    response.say(questions_and_responses[0]["question"])
    
    gather = Gather(action='/handle_response', method='POST', input='speech')
    response.append(gather)
    
    return Response(content=str(response), media_type="application/xml")

@app.post("/handle_response")
async def handle_response(request: Request):
    from_number = request.query_params.get('From')
    current_index = current_question_index.get(from_number, 0)
    speech_result = request.query_params.get('SpeechResult')
    
    response = VoiceResponse()
    response.say(questions_and_responses[current_index]["response"])

    current_index += 1
    current_question_index[from_number] = current_index

    if current_index < len(questions_and_responses):
        response.say(questions_and_responses[current_index]["question"])
        gather = Gather(action='/handle_response', method='POST', input='speech')
        response.append(gather)
    else:
        response.say("Thank you for your time. Goodbye!")
        response.hangup()
    
    return Response(content=str(response), media_type="application/xml")

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
