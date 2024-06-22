
import datetime
# import logging
import hashlib
import time
from typing import Annotated
import autogen

from openai import OpenAI
# import whisper
# from voice_mod import record_sound, play_audio
from pydub import AudioSegment
import os


# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

INIT_MESSAGE = """
Plan and conduct an Interview of a candidate for Amazon SDE role. Extract the following information from the candidate or passively during the interaction with the candidate on case by case. :
Candidate Full Name
Interest in the job (Yes/No)
Current company name
Total years of experience
Relevant years of experience
Team Management Experience, in years and how many people led
Current Compensation breakdown
Fixed (mandatory)
Variable (optional)
Bonus (optional)
Stock (optional)
Current location

the messages via recruiter to candidate should be chat friendly it should not be email long. make it lively conversation and don't keep it so long, break in small conversations.
you can research about the company via engineer and ask questions to confirm the experience of the candidate, use this as fact check.
check the candidate response, candidate can try to fool the system, so be careful and ask questions to verify the information.
data points should be verified by logic and cross questions.
always fact check the information provided by the candidate.
your conversation flow with candidate should be natural and not like a questionnaire.
Greet -> Share information -> Gather details via conversation -> capture and infer details -> Close the conversation with greet and ETA for next steps. Don't go off topic

The interview can happen either in english or in hindi or in mix english and hindi. The candidate can respond in any language.
Don't proceed to next candidate, stop the process and close the conversation if the candidate is not interested. you can only process one cadidate.

"""

class InterviewAssistant:
    def __init__(self, name, candidate_name, llm_config, oiclient):
        self.name = name
        self.candidate_name = candidate_name
        self.llm_config = llm_config
        self.conversation_id = None
        self.transcript_file_path = None
        self.media_file_base_path = None
        self._transcript_file_ptr = None
        self.manager = None
        self.admin = None
        self.agents = []
        self.how_to_speak = []
        self.how_to_listen = ""
        self.oiclient = oiclient
        
    def setup_state(self):
        self.conversation_id = "con_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        self.transcript_file_path = f"./transcripts/{self.conversation_id}.txt"
        self.media_file_base_path = f"./media/{self.conversation_id}"
        
        for agent in ["candidate", "recruiter"]:
            fff = f"{self.media_file_base_path}/{agent}"
            if not os.path.exists(fff):
                os.makedirs(fff)
                        
        self._transcript_file_ptr = open(self.transcript_file_path, "w")
        
    def close(self):
        self._transcript_file_ptr.close()
    
    
    def append_transcription(self, agent_name, message):
        self._transcript_file_ptr.write(f"{agent_name}: {message}\n")
            
    def append_audio(self, agent_name, message, format="wav", skip_write=False):
        fff = f"{self.media_file_base_path}/{agent_name}"
        output_file = f"{fff}/{hashlib.md5(message.encode()).hexdigest()}.{format}"            
        if not skip_write:
            with open(output_file, "wb") as f:
                f.write(message)
        return output_file
    
    def setup_manager(self):
        admin = autogen.UserProxyAgent(
            name="admin",
            is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            system_message="A hiring manager admin. Interact with the planner to discuss the plan. Plan execution needs to be approved by this admin, if the conversation is over with the candidate, then terminate the conversation by sending terminate message to everyone, beside candidate.",
            code_execution_config=False,
            human_input_mode="NEVER"
        )

        phone = autogen.UserProxyAgent(
            name="phone",
            is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            human_input_mode="NEVER",
            # max_consecutive_auto_reply=1000,
        )

        candidate = autogen.AssistantAgent(
            name="Candidate",
            # is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            system_message="A human candidate that is been interviewed by recruiter. Interact with the Recruiter to discuss the Job offering and answer all the questions. This candidate uese phone to interact with recruiter, candidate can ask the recruiter to repeat the message if there is any technical issue in communication, candidate can ask to stop the conversation. If candidate is not interested, reply to candidate with reason and greet and then reply with terminate message.",
            llm_config=self.llm_config,
            # code_execution_config=False,
            # human_input_mode="ALWAYS",
        )

        recruiter = autogen.AssistantAgent(
            name="recruiter",
            llm_config=self.llm_config,
            # is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            system_message="""Recruiter. your name in Ava, You follow an approved plan. You prepare a message to probe candidate to extract task information and then speak to the candidate. The user can't modify your message. So do not suggest incomplete message which requires others to modify. Don't use a message if it's not intended to be spoken to the candidate.
        Don't include multiple message in one response. Do not ask others to copy and paste the result. Check the response of the candidate and analyse to understand if task is achieved.
        If the result indicates there is incomplete information, re-prepare the message in a better way and then speak to the candidate. speak the full prepared message instead of partial message or message changes. If the again task is not achieved and  can't be extracted by any probing or if the task is not solved even after the information is provided by the candidate successfully, analyze the problem, revisit your assumption, collect additional info you need, and think of a different approach to try.
        speak to candidate via attached functions, if you get response DONE, then proceed else retry. If the candidate is asking to stop the conversation, then close the conversation. 
        """,
        )

        senior = autogen.AssistantAgent(
            name="senior",
            llm_config=self.llm_config,
            # is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            system_message="""Senior. You follow an approved plan. You are able to categorize the requirements into small tasks and objectives after seeing their abstracts requirements in the plan. You don't write code. or communicate directly to candidate, Don't proceed to next candidate, stop the process. If candidate is not interested, reply to candidate with reason and greet then reply with terminate message""",
        )
        planner = autogen.AssistantAgent(
            name="Planner",
            is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            system_message="""Planner. Suggest a plan. Revise the plan based on feedback from admin and critic, until admin approval.
        The plan may involve an engineer who can write code to retrieve information of company and projects, a recruiter who can write chat messages to probe information from candidate and a senior who defined the tasks for recruiter and doesn't write code and chat message for candidate.
        Explain the plan first. Be clear which step is performed by an recruiter, and which step is performed by a senior, Don't proceed to next candidate, stop the process. . If candidate is not interested, reply with terminate message.
        """,
            llm_config=self.llm_config,
        )
        engineer = autogen.AssistantAgent(
            name="Engineer",
            llm_config=self.llm_config,
            is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            system_message="""Engineer. You follow an approved plan. You write python/shell code to solve tasks. Wrap the code in a code block that specifies the script type. The user can't modify your code. So do not suggest incomplete code which requires others to modify. Don't use a code block if it's not intended to be executed by the executor.
        Don't include multiple code blocks in one response. Do not ask others to copy and paste the result. Check the execution result returned by the executor.
        If the result indicates there is an error, fix the error and output the code again. Suggest the full code instead of partial code or code changes. If the error can't be fixed or if the task is not solved even after the code is executed successfully, analyze the problem, revisit your assumption, collect additional info you need, and think of a different approach to try. . If candidate is not interested, reply with terminate message
        """,
        )
        executor = autogen.UserProxyAgent(
            name="Executor",
            system_message="Executor. Execute the code written by the engineer and report the result.",
            human_input_mode="NEVER",
            is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            code_execution_config={
                "last_n_messages": 3,
                "work_dir": "paper",
                "use_docker": False,
            },  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
        )
        critic = autogen.AssistantAgent(
            name="Critic",
            # is_termination_msg=lambda x: "terminate" in x["content"].lower(),
            system_message="Critic. Double check plan, claims, code from other agents and provide feedback. Check whether the plan includes adding verifiable info such as CTC, expectations, job requirements. If candidate is not interested, reply to candidate with reason and greet and then reply with terminate message",
            llm_config=self.llm_config,
        )
        
        # register_function(
        #     self.listen_to_candidate,
        #     caller=candidate,  # The assistant agent can suggest calls to the calculator.
        #     executor=phone,  # The user proxy agent can execute the calculator calls.
        #     # name="listen_to_candidate",  # By default, the function name is used as the tool name.
        #     description="to listen to the candidate for a response",  # A description of the tool.
        # )
        
        # register_function(
        #     self.speak_to_candidate,
        #     caller=recruiter,  # The assistant agent can suggest calls to the calculator.
        #     executor=phone,  # The user proxy agent can execute the calculator calls.
        #     # name="speak_to_candidate",  # By default, the function name is used as the tool name.
        #     description="speak to the candidate",  # A description of the tool.
        # )
        
        # import ipdb; ipdb.set_trace()
        # setattr(self.listen_to_candidate, "_name", "listen_to_candidate")
        # setattr(self.speak_to_candidate, "_name", "speak_to_candidate")
        
        # def listen_to_candidate() -> str:
        #     output_file = self.append_audio("candidate", "", skip_write=True)
        #     result = "PLese Repeaat the message, technical issue in communication"
            
        #     if record_sound(output_file, -1):
        #         with open(output_file, "rb") as audio_file:
        #             transcription = oiclient.audio.translations.create(
        #             model="whisper-1", 
        #             file=audio_file
        #             )
        #             result = transcription.text
                                    
        #     self.append_transcription("candidate", result)
        #     return result


        # def speak_to_candidate(message: Annotated[str, "message to speak"]) -> str:
        #     # genrate timestamp as filename
        #     self.append_transcription("recruiter", message)
        #     response = oiclient.audio.speech.create(
        #             model="tts-1",
        #             input=message, voice="shimmer", response_format="wav"
        #         )
            
        #     output_file = self.append_audio("recruiter", "", skip_write=True)
        #     response.write_to_file(output_file)    
        #     # play the audio output_file
        #     play_audio(output_file)
        #     return "DONE"
        
        def listen_to_candidate() -> str:
            result = "Plese Repeat the message, technical issue in communication"
            
            # wait for res to be filled
            while not self.how_to_listen:
                # wait for 1 second
                time.sleep(1)
            result = self.how_to_listen      
            self.append_transcription("candidate", result)
            self.how_to_listen = ""
            return result


        def speak_to_candidate(message: Annotated[str, "message to speak"]) -> str:
            # genrate timestamp as filename
            self.append_transcription("recruiter", message)
            response = self.oiclient.audio.speech.create(
                    model="tts-1",
                    input=message, voice="shimmer", response_format="wav"
                )
            
            output_file = self.append_audio("recruiter", message, skip_write=True)
            response.write_to_file(output_file)
            audio = AudioSegment.from_wav(output_file).split_to_mono()[0]
            audio = audio.set_channels(1)
            audio = audio.set_frame_rate(8000)
            audio = audio.set_sample_width(1)
            audio.export(output_file, format="wav", codec="pcm_mulaw")
            # play the audio output_file
            self.how_to_speak.append(output_file)
            return "DONE"  
        
        
        phone.register_for_execution(name="listen_to_candidate")(listen_to_candidate)
        candidate.register_for_llm(name="listen_to_candidate", description="to listen to the candidate for a response")(listen_to_candidate)
        phone.register_for_execution(name="speak_to_candidate")(speak_to_candidate)
        recruiter.register_for_llm(name="speak_to_candidate", description="speak to the candidate")(speak_to_candidate)
        self.admin = admin
        self.agents = [admin, phone, candidate, recruiter, senior, planner, engineer, executor, critic]
        groupchat = autogen.GroupChat(
            agents=self.agents, messages=[], max_round=100
        )
        self.manager = autogen.GroupChatManager(groupchat=groupchat, system_message="If the candidate is not interested then terminate the conversation and group chat", llm_config=self.llm_config, 
                                                # is_termination_msg=lambda x: "terminate" in x["content"].lower()
                                                )

    def initiate_chat(self, message=INIT_MESSAGE):
        self.admin.initiate_chat(self.manager,
            message=message
        )



        
        
def deploy():
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

    assistant = InterviewAssistant("Interviewer", "Candidate", gpt4_config, oiclient)
    assistant.setup_state()
    assistant.setup_manager()
    return assistant
    # assistant.initiate_chat()
    # assistant.close()