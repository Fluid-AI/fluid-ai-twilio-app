from fastapi import HTTPException, Request, Response, FastAPI, Depends, WebSocket, WebSocketDisconnect
from services import validate_request, generate_websocket_signature, verify_websocket_signature
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
import traceback
import urllib
import json
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from loguru import logger
from agent_takeover import transfer_call_to_agent

assets_path = Path(__file__).parent / 'assets'

app = FastAPI(
    title="Voice call service App",
    description="It allows uses to send queries via phone and get answers from FluidGPT engine",
    version="1.0.0",
    servers=[]
)

app.mount("/static", StaticFiles(directory=assets_path), name="voicecall-assets")

filler_words = ["um", "ah", "hmm", "like", "you know","alright"]

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # This handles incoming calls live audio streams from Twilio
    try:
        await websocket.accept()
        closed = False
        is_request_valid = False

        while not closed:
            message = await websocket.receive_text()
            
            data = json.loads(message)
            if data["event"] == "connected":
                continue
            if data["event"] == "start":
                details = data["start"]
                # Custom parameters contains, chat id, language, mode, tools, agent type and mobile number
                customParameters = details["customParameters"]
                logger.info(f"Custom parameters: {customParameters}")
                # Request validation if it is actually coming from Twilio only
                is_request_valid = verify_websocket_signature(chat_id=customParameters["chat_id"], call_sid=details["callSid"], mobile=customParameters["mobile"], signature=customParameters["X-Fluid-Signature"])

                logger.info(f"Request is valid: {is_request_valid}")
                
                continue
            if not is_request_valid:
                break
            if data["event"] == "media":
                pass
            if data["event"] == "dtmf":
                dtmf_tone = data['dtmf']['digit']
                logger.info(f"DTMF: {data['dtmf']['digit']}")
                if dtmf_tone == "#":
                    # Transfer the call to an agent
                    transfer_call_to_agent(call_sid=details["callSid"], chat_id=customParameters["chat_id"])
            if data["event"] == "stop":
                closed = True
    except WebSocketDisconnect:
        traceback.print_exc()
    except Exception:
        traceback.print_exc()
    finally:
        await websocket.close()

# create a global datastore variable
datastore = None

@app.get("/is-alive", summary="This endpoint is used to check if the server is alive.")
def is_alive():
    return "Alive"

@app.post("/webhook/receive-call", 
              summary="This handles incoming calls to the mobile number, when the number is dialed and a call is received",
              dependencies=[Depends(validate_request)])
async def receive_call(request: Request, mode: str | None = None, tools: str | None = None, agent_type: str | None = None, stream: bool = False, language: str = "en-US"):
    # This webhook is triggered by Twilio after a call is received or picked up for the given Twilio mobile number
    try:
        # Get client IP address from X-Real-IP header if available, else use request.client.host
        client_ip = request.headers.get('X-Real-IP', request.client.host)

        # Extract headers and query parameters
        headers = request.headers
        query_params = request.query_params

        # Get request body (read it once and use it as necessary)
        body = request.state.body
        logger.info(f"Incoming request: {request.method} {request.url} from {client_ip}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Query Params: {query_params}")
        logger.info(f"Body: {body}")

        call_direction = body.get('Direction')
        mobile = body.get('To') if call_direction == 'outbound-api' else body.get('From')
        call_sid = body.get('CallSid')

        chat_id = "ChatID"
        query_params = { "chat_id": chat_id, "language": language }
        if mode:
            query_params['mode'] = mode
        if tools:
            query_params['tools'] = tools
        if agent_type:
            query_params['agent_type'] = agent_type

        query_str = urllib.parse.urlencode(query_params)
        response = VoiceResponse()
        
        # As soon as the call is picked we speak welcome message to start the conversation
        file_name = f"welcome_en-US.mp3"
        response.play(f'https://{request.headers["Host"]}/static/{file_name}')

        # Streaming requests are handled through websockets
        connect = Connect()
        stream = Stream(url=f'wss://{request.headers["Host"]}/ws')

        for q in query_params:
            stream.parameter(name=q, value=query_params[q])

        stream.parameter(name="mobile", value=mobile)
        stream.parameter(name="X-Fluid-Signature", value=generate_websocket_signature(chat_id=chat_id, call_sid=call_sid, mobile=mobile))
        connect.append(stream)
        response.append(connect)
        
        return Response(content=str(response), media_type="text/xml")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal Server Error")

    
@app.post("/webhook/refer-callback", 
              summary="This runs when a sip transfer/refer request is made to switch the call to an active agent, this will receive the status of the call transfer",
              dependencies=[Depends(validate_request)])
async def refer_callback(chat_id: str, destination_address: str, request: Request):
    try:
        logger.info(dir(request))
        logger.info(f"request.state: {dir(request.state)}")
        body = request.state.body
        logger.info(f"body: {body}")
        refer_call_status = body.get("ReferCallStatus")
        logger.info(f"refer_call_status: {refer_call_status}")
        refer_sip_response_code = body.get("ReferSipResponseCode")
        logger.info(f"refer_sip_response_code: {refer_sip_response_code}")
        nofity_sip_response_code = body.get("NotifySipResponseCode")
        logger.info(f"nofity_sip_response_code: {nofity_sip_response_code}")
        logger.info(f"destination_address: {destination_address}")
        if refer_call_status == "in-progress" and refer_sip_response_code == "202" and nofity_sip_response_code == "200":
            logger.info("Call transfer successful")
        return """<?xml version="1.0" encoding="UTF-8"?>"""
    except HTTPException as e:
        traceback.print_exc()
        raise e
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.post("/webhook/status-callback", dependencies=[Depends(validate_request)])
async def status_callback(request: Request):
    """
        Handle status callbacks from Twilio webhook.
        Parameters:
        - request: FastAPI Request object containing webhook data.

    """
    try:        
        # Extract the request body stored
        body = request.state.body

        # Retrieve relevant call details from the request body
        call_status = body.get('CallStatus') # incoming call status after call completion
        call_sid = body.get('CallSid') # call sid
        call_direction = body.get('Direction') #call direction

        # Log the call status
        logger.info(f"Call status: {call_status}")
        logger.info(f"Call SID: {call_sid}")
        logger.info(f"Call Direction: {call_direction}")
                            
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal Server Error")
