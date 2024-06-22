from asyncio import sleep
import datetime
import hashlib
import tempfile
from typing import Annotated
import autogen
from openai import OpenAI
import whisper
from voice_mod import record_sound, play_audio
import os




api_key = os.getenv("OPENAI_API_KEY")
oiclient = OpenAI(api_key=api_key)
openai_config = {"model": "gpt-4o", "api_key": api_key}
config_list = [
  {
    "model": "llama3",
    "base_url": "http://localhost:11434/v1",
    "api_key": "ollama",
  }
]

gpt4_config = {
                "cache_seed": 42,  # change the cache_seed for different trials
                "temperature": 0,
                "config_list":  [openai_config] or config_list,
                "timeout": 120,
            }

conversation_id, transcript_file_path, media_file_base_path, _transcript_file_ptr = None, None, None, None
        
def setup_state():
    global conversation_id, transcript_file_path, media_file_base_path, _transcript_file_ptr
    conversation_id = "con_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    transcript_file_path = f"./transcripts/{conversation_id}.txt"
    media_file_base_path = f"./media/{conversation_id}"
    
    for agent in ["candidate", "recruiter"]:
        fff = f"{media_file_base_path}/{agent}"
        if not os.path.exists(fff):
            os.makedirs(fff)
                    
    _transcript_file_ptr = open(transcript_file_path, "w")
    
    # import ipdb; ipdb.set_trace()
setup_state()    

def close():
    _transcript_file_ptr.close()
    
def append_transcription(agent_name, message):
    _transcript_file_ptr.write(f"{agent_name}: {message}\n")
        
def append_audio(agent_name, message, format="wav", skip_write=False):
    fff = f"{media_file_base_path}/{agent_name}"
    output_file = f"{fff}/{hashlib.md5(message.encode()).hexdigest()}.{format}"            
    if not skip_write:
        with open(output_file, "wb") as f:
            f.write(message)
    return output_file


admin = autogen.UserProxyAgent(
    name="Admin",
    system_message="A hiring manager admin. Interact with the planner to discuss the plan. Plan execution needs to be approved by this admin.",
    code_execution_config=False,
)

phone = autogen.UserProxyAgent(
    name="phone",
    is_termination_msg=lambda x: x.get("content", "") and x.get("content", "").rstrip().endswith("TERMINATE"),
    human_input_mode="NEVER",
    # max_consecutive_auto_reply=1000,
)

candidate = autogen.AssistantAgent(
    name="Candidate",
    system_message="A human candidate that is been interviewed by recruiter. Interact with the Recruiter to discuss the Job offering and answer all the questions. This candidate uese phone to interact with recruiter",
    llm_config=gpt4_config,
    # code_execution_config=False,
    # human_input_mode="ALWAYS",
)

recruiter = autogen.AssistantAgent(
    name="recruiter",
    llm_config=gpt4_config,
    system_message="""Recruiter. your name in Ava, You follow an approved plan. You prepare a message to probe candidate to extract task information and then speak to the candidate. The user can't modify your message. So do not suggest incomplete message which requires others to modify. Don't use a message if it's not intended to be spoken to the candidate.
Don't include multiple message in one response. Do not ask others to copy and paste the result. Check the response of the candidate and analyse to understand if task is achieved.
If the result indicates there is incomplete information, re-prepare the message in a better way and then speak to the candidate. speak the full prepared message instead of partial message or message changes. If the again task is not achieved and  can't be extracted by any probing or if the task is not solved even after the information is provided by the candidate successfully, analyze the problem, revisit your assumption, collect additional info you need, and think of a different approach to try.
speak to candidate via attached functions, if you get response DONE, then proceed else retry.
""",
)

senior = autogen.AssistantAgent(
    name="senior",
    llm_config=gpt4_config,
    system_message="""Senior. You follow an approved plan. You are able to categorize the requirements into small tasks and objectives after seeing their abstracts requirements in the plan. You don't write code. or communicate directly to candidate""",
)
planner = autogen.AssistantAgent(
    name="Planner",
    system_message="""Planner. Suggest a plan. Revise the plan based on feedback from admin and critic, until admin approval.
The plan may involve an engineer who can write code to retrieve information of company and projects, a recruiter who can write chat messages to probe information from candidate and a senior who defined the tasks for recruiter and doesn't write code and chat message for candidate.
Explain the plan first. Be clear which step is performed by an recruiter, and which step is performed by a senior.
""",
    llm_config=gpt4_config,
)
engineer = autogen.AssistantAgent(
    name="Engineer",
    llm_config=gpt4_config,
    system_message="""Engineer. You follow an approved plan. You write python/shell code to solve tasks. Wrap the code in a code block that specifies the script type. The user can't modify your code. So do not suggest incomplete code which requires others to modify. Don't use a code block if it's not intended to be executed by the executor.
Don't include multiple code blocks in one response. Do not ask others to copy and paste the result. Check the execution result returned by the executor.
If the result indicates there is an error, fix the error and output the code again. Suggest the full code instead of partial code or code changes. If the error can't be fixed or if the task is not solved even after the code is executed successfully, analyze the problem, revisit your assumption, collect additional info you need, and think of a different approach to try.
""",
)
executor = autogen.UserProxyAgent(
    name="Executor",
    system_message="Executor. Execute the code written by the engineer and report the result.",
    human_input_mode="NEVER",
    code_execution_config={
        "last_n_messages": 3,
        "work_dir": "paper",
        "use_docker": False,
    },  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
)
critic = autogen.AssistantAgent(
    name="Critic",
    system_message="Critic. Double check plan, claims, code from other agents and provide feedback. Check whether the plan includes adding verifiable info such as CTC, expectations, job requirements.",
    llm_config=gpt4_config,
)

@phone.register_for_execution()
@candidate.register_for_llm(description="to listen to the candidate for a response")
def listen_to_candidate() -> str:
    output_file = append_audio("candidate", "", skip_write=True)
    result = "PLese Repeaat the message, technical issue in communication"
    
    if record_sound(output_file, -1):
        with open(output_file, "rb") as audio_file:
            transcription = oiclient.audio.translations.create(
            model="whisper-1", 
            file=audio_file
            )
            result = transcription.text
                            
    append_transcription("candidate", result)
    return result


@phone.register_for_execution()
@recruiter.register_for_llm(description="speak to the candidate")
def speak_to_candidate(
    message: Annotated[str, "message to speak"]) -> str:
    # genrate timestamp as filename
    append_transcription("recruiter", message)
    response = oiclient.audio.speech.create(
            model="tts-1",
            input=message, voice="shimmer", response_format="wav"
        )
    
    output_file = append_audio("recruiter", "", skip_write=True)
    response.write_to_file(output_file)    
    # play the audio output_file
    play_audio(output_file)
    return "DONE"

agents = [admin, phone, candidate, recruiter, senior, planner, engineer, executor, critic]
groupchat = autogen.GroupChat(
    agents=agents, messages=[], max_round=100
)
manager = autogen.GroupChatManager(groupchat=groupchat, llm_config=gpt4_config)






admin.initiate_chat(
    manager,
    message="""
Plan and conduct an Interview of a candidate for Amazon SDE role. Extract the following information from the candidate or passively during the interaction with the candidate on case by case. :
Candidate Name
Interest in the job (Yes/No)
Current company name
Total years of experience
Relevant years of experience
Team Management Experience, in years and how many people led
Current Compensation breakdown
Fixed
Variable
Bonus
Stock
Current location

the messages via recruiter to candidate should be chat friendly it should not be email long. make it lively conversation and don't keep it so long, break in small conversations.
you can research about the company via engineer and ask questions to confirm the experience of the candidate, use this as fact check.
check the candidate response, candidate can try to fool the system, so be careful and ask questions to verify the information.
data points should be verified by logic and cross questions.
always fact check the information provided by the candidate.
your conversation flow with candidate should be natural and not like a questionnaire.
Greet -> Share information -> Gather details via conversation -> capture and infer details -> Close the conversation with greent and ETA for next steps. Don't go off topic

The interview can happen either in english or in hindi or in mix english and hindi. The candidate can respond in any language.
"""
)